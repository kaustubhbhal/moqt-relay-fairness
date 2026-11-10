// SPDX-FileCopyrightText: 2026 MoQT Relay Fairness project contributors
// SPDX-License-Identifier: MIT
use anyhow::{bail, ensure, Context, Result};
use bytes::Bytes;
use clap::{Args, Parser, Subcommand};
use futures::{stream::FuturesUnordered, StreamExt};
use moq_transport::{
    coding::{KeyValuePairs, TrackNamespace},
    serve::{Track, TrackReader, TrackReaderMode},
    session::{Publisher, Session, SessionId, Subscriber, Transport},
};
use serde_json::{json, Value};
use std::{
    io::{self, Write},
    path::PathBuf,
    sync::Arc,
    time::{Duration, SystemTime, UNIX_EPOCH},
};
use tokio::time::{self, Instant};
use url::Url;

#[derive(Parser)]
#[command(about = "Native real-QUIC draft-16 media load experiment")]
struct Cli {
    #[command(subcommand)]
    command: Command,
}
#[derive(Subcommand)]
enum Command {
    Publish(PublishArgs),
    Subscribe(SubscribeArgs),
}
#[derive(Args, Clone)]
struct Common {
    #[arg(long, default_value = "moqt://127.0.0.1:4443")]
    relay: Url,
    #[arg(long)]
    tls_root: PathBuf,
    #[arg(long, default_value = "experiment")]
    namespace: String,
    /// Measurement duration starts after this endpoint's protocol acknowledgement.
    #[arg(long, default_value_t = 30.0)]
    duration: f64,
}
#[derive(Args)]
struct PublishArgs {
    #[command(flatten)]
    common: Common,
    #[arg(long, default_value_t = 4_000_000)]
    bitrate: u64,
    #[arg(long, default_value_t = 30)]
    fps: u64,
    #[arg(long, default_value_t = 30)]
    group_frames: u64,
}
#[derive(Args, Clone)]
struct SubscribeArgs {
    #[command(flatten)]
    common: Common,
    #[arg(long, default_value_t = 1)]
    clients: usize,
    #[arg(long, default_value_t = 0)]
    client_offset: usize,
    #[arg(long, default_value_t = 0)]
    stall_clients: usize,
    #[arg(long, default_value_t = 5.0)]
    stall_after: f64,
    #[arg(long, default_value_t = 3.0)]
    stall_for: f64,
    #[arg(long, default_value_t = 65536)]
    receive_window: u64,
    #[arg(long, default_value_t = 32768)]
    stream_receive_window: u64,
    /// Bound concurrent receive subgroups to avoid the pinned latest-reader cache race.
    #[arg(long, default_value_t = 1)]
    max_uni_streams: u32,
}
fn unix_us() -> Result<u64> {
    Ok(SystemTime::now()
        .duration_since(UNIX_EPOCH)?
        .as_micros()
        .try_into()?)
}
fn emit(v: Value) -> Result<()> {
    let mut out = io::stdout().lock();
    serde_json::to_writer(&mut out, &v)?;
    writeln!(&mut out)?;
    out.flush()?;
    Ok(())
}
fn duration(value: f64) -> Result<Duration> {
    ensure!(
        value.is_finite() && value >= 0.0,
        "duration must be finite and nonnegative"
    );
    Duration::try_from_secs_f64(value).context("invalid duration")
}
const HEADER: usize = 32;
fn payload(seq: u64, sent: u64, size: usize) -> Result<Bytes> {
    ensure!(size >= HEADER, "object too small for experiment header");
    let mut p = vec![0xa5; size];
    p[..8].copy_from_slice(b"MOQEXP01");
    p[8..16].copy_from_slice(&seq.to_be_bytes());
    p[16..24].copy_from_slice(&sent.to_be_bytes());
    p[24..32].copy_from_slice(&(size as u64).to_be_bytes());
    Ok(Bytes::from(p))
}
fn parse_payload(p: &[u8]) -> Result<(u64, u64)> {
    ensure!(
        p.len() >= HEADER && &p[..8] == b"MOQEXP01",
        "invalid experiment payload header"
    );
    let seq = u64::from_be_bytes(p[8..16].try_into()?);
    let sent = u64::from_be_bytes(p[16..24].try_into()?);
    let size = u64::from_be_bytes(p[24..32].try_into()?);
    ensure!(
        size == p.len() as u64,
        "truncated or oversized experiment payload"
    );
    ensure!(
        p[HEADER..].iter().all(|b| *b == 0xa5),
        "experiment payload corrupt"
    );
    Ok((seq, sent))
}

struct Connected {
    _endpoint: quinn::Endpoint,
    connection: quinn::Connection,
    session: Session,
    publisher: Publisher,
    subscriber: Subscriber,
}
async fn connect(common: &Common, windows: Option<(u64, u64, u32)>) -> Result<Connected> {
    ensure!(
        common.relay.scheme() == "moqt",
        "this experiment uses raw QUIC; expected moqt:// URL"
    );
    let host = common.relay.host_str().context("relay host missing")?;
    let port = common.relay.port().unwrap_or(443);
    let address = tokio::net::lookup_host((host, port))
        .await?
        .next()
        .context("relay DNS empty")?;
    let tls = moq_native_ietf::tls::Args {
        root: vec![common.tls_root.clone()],
        ..Default::default()
    }
    .load()?;
    let mut crypto = tls.client;
    crypto.alpn_protocols = vec![moq_transport::setup::ALPN.to_vec()];
    let mut cfg = quinn::ClientConfig::new(Arc::new(
        quinn::crypto::rustls::QuicClientConfig::try_from(crypto)?,
    ));
    let mut transport = quinn::TransportConfig::default();
    transport.max_idle_timeout(Some(Duration::from_secs(10).try_into()?));
    transport.keep_alive_interval(Some(Duration::from_secs(2)));
    transport.congestion_controller_factory(Arc::new(quinn::congestion::BbrConfig::default()));
    transport.mtu_discovery_config(None);
    if let Some((connection, stream, max_uni_streams)) = windows {
        ensure!(max_uni_streams > 0, "max-uni-streams must be positive");
        transport.max_concurrent_uni_streams(max_uni_streams.into());
        ensure!(
            connection >= HEADER as u64 && stream >= HEADER as u64,
            "receive windows must be at least 32 bytes"
        );
        transport.receive_window(connection.try_into()?);
        transport.stream_receive_window(stream.try_into()?);
    }
    cfg.transport_config(Arc::new(transport));
    let bind = if address.is_ipv4() {
        "0.0.0.0:0"
    } else {
        "[::]:0"
    };
    let mut endpoint = quinn::Endpoint::client(bind.parse()?)?;
    endpoint.set_default_client_config(cfg);
    let connection = endpoint.connect(address, host)?.await?;
    let sid = format!("experiment-{}", connection.stable_id());
    let raw = web_transport_quinn::Session::raw(
        connection.clone(),
        common.relay.clone(),
        web_transport_quinn::proto::ConnectResponse::default(),
    );
    let (session, publisher, subscriber) =
        Session::connect_with_session_id(raw.into(), SessionId::new(sid), None, Transport::RawQuic)
            .await?;
    Ok(Connected {
        _endpoint: endpoint,
        connection,
        session,
        publisher,
        subscriber,
    })
}
fn stats(conn: &quinn::Connection, client: usize, cohort: &str, phase: &str) -> Result<()> {
    let s = conn.stats();
    emit(
        json!({"type":"quic_stats","client":client,"cohort":cohort,"phase":phase,"timestamp_unix_us":unix_us()?,"udp_rx_bytes":s.udp_rx.bytes,"udp_tx_bytes":s.udp_tx.bytes,"rx_stream_frames":s.frame_rx.stream,"rx_data_blocked":s.frame_rx.data_blocked,"rx_stream_data_blocked":s.frame_rx.stream_data_blocked,"tx_max_data":s.frame_tx.max_data,"tx_max_stream_data":s.frame_tx.max_stream_data,"tx_acks":s.frame_tx.acks,"rtt_us":s.path.rtt.as_micros() as u64,"lost_packets":s.path.lost_packets}),
    )
}
async fn publish(args: PublishArgs) -> Result<()> {
    ensure!(
        args.fps > 0 && args.group_frames > 0,
        "fps and group-frames must be positive"
    );
    let denominator = args.fps.checked_mul(8).context("fps overflow")?;
    let size: usize = (args.bitrate / denominator).try_into()?;
    ensure!(
        (HEADER..=16 * 1024 * 1024).contains(&size),
        "object size must be 32 bytes to 16 MiB"
    );
    let measurement = duration(args.common.duration)?;
    let Connected {
        _endpoint,
        connection,
        session,
        mut publisher,
        ..
    } = time::timeout(Duration::from_secs(15), connect(&args.common, None)).await??;
    emit(json!({"type":"connection","role":"publisher","timestamp_unix_us":unix_us()?}))?;
    let (writer, reader) = Track::new(
        TrackNamespace::from_utf8_path(&args.common.namespace),
        "video",
    )
    .produce();
    let run = session.run();
    tokio::pin!(run);
    let mut published = publisher.publish(reader, KeyValuePairs::default()).await?;
    tokio::select! {
        r=published.ok()=>r?,
        r=&mut run=>{r?;bail!("session ended during publish setup")},
        _=time::sleep(Duration::from_secs(15))=>bail!("publish acknowledgement timed out"),
    }
    emit(
        json!({"type":"ready","role":"publisher","publish_mode":"direct_publish","timestamp_unix_us":unix_us()?,"duration":args.common.duration,"bitrate":args.bitrate,"actual_bitrate":size as u64*denominator,"fps":args.fps,"group_frames":args.group_frames,"object_bytes":size}),
    )?;
    let mut subgroups = writer.subgroups()?;
    let generate = async {
        let mut ticker = time::interval(Duration::from_secs_f64(1.0 / args.fps as f64));
        ticker.set_missed_tick_behavior(time::MissedTickBehavior::Skip);
        let end = Instant::now() + measurement;
        let mut group = None;
        let mut seq = 0u64;
        loop {
            tokio::select! { biased; _=time::sleep_until(end)=>break, _=ticker.tick()=>{} }
            if seq.is_multiple_of(args.group_frames) {
                group = Some(subgroups.append(128)?);
            }
            let sent = unix_us()?;
            group
                .as_mut()
                .context("missing subgroup")?
                .write(payload(seq, sent, size)?)?;
            emit(json!({"type":"published","seq":seq,"bytes":size,"sent_unix_us":sent}))?;
            seq += 1;
        }
        emit(
            json!({"type":"complete","role":"publisher","objects":seq,"timestamp_unix_us":unix_us()?}),
        )?;
        Ok::<_, anyhow::Error>(())
    };
    tokio::select! {
        r=generate=>r?,
        r=published.serve()=>{r?;bail!("publisher forwarding ended early")},
        r=&mut run=>{r?;bail!("publisher session ended early")},
    }
    connection.close(0u32.into(), b"experiment complete");
    Ok(())
}
async fn receive(reader: TrackReader, client: usize, cohort: &str) -> Result<()> {
    let mut subgroups = match reader.mode().await? {
        TrackReaderMode::Subgroups(s) => s,
        _ => bail!("expected subgroup delivery"),
    };
    let mut tasks = FuturesUnordered::new();
    loop {
        tokio::select! {
            item=subgroups.next()=>{
                let Some(mut subgroup)=item? else { bail!("track ended") };
                tasks.push(async move {
                    while let Some(bytes)=subgroup.read_next().await? {
                        let received=unix_us()?;
                        let (seq,sent)=parse_payload(&bytes)?;
                        let latency=(received as i128-sent as i128) as f64/1000.0;
                        emit(json!({"type":"object","client":client,"cohort":cohort,"seq":seq,"bytes":bytes.len(),"sent_unix_us":sent,"received_unix_us":received,"latency_ms":latency}))?;
                    }
                    Ok::<_,anyhow::Error>(())
                });
            },
            result=tasks.next(),if !tasks.is_empty()=>{if let Some(r)=result {r?;}},
        }
    }
}
async fn subscriber(args: SubscribeArgs, index: usize) -> Result<()> {
    let client = args.client_offset + index;
    let stalled = index < args.stall_clients;
    let cohort = if stalled { "stalled" } else { "healthy" };
    let Connected {
        _endpoint,
        connection,
        session,
        mut subscriber,
        ..
    } = time::timeout(
        Duration::from_secs(15),
        connect(
            &args.common,
            Some((
                args.receive_window,
                args.stream_receive_window,
                args.max_uni_streams,
            )),
        ),
    )
    .await??;
    emit(
        json!({"type":"connection","role":"subscriber","client":client,"cohort":cohort,"timestamp_unix_us":unix_us()?}),
    )?;
    let (writer, reader) = Track::new(
        TrackNamespace::from_utf8_path(&args.common.namespace),
        "video",
    )
    .produce();
    let run = session.run();
    tokio::pin!(run);
    let subscription = tokio::select! {
        r=subscriber.subscribe_open(writer)=>r?,
        r=&mut run=>{r?;bail!("session ended during subscribe setup")},
        _=time::sleep(Duration::from_secs(15))=>bail!("subscribe acknowledgement timed out"),
    };
    emit(
        json!({"type":"ready","role":"subscriber","client":client,"cohort":cohort,"timestamp_unix_us":unix_us()?,"duration":args.common.duration,"stall_after":args.stall_after,"stall_for":args.stall_for,"receive_window":args.receive_window,"stream_receive_window":args.stream_receive_window,"max_uni_streams":args.max_uni_streams}),
    )?;
    stats(&connection, client, cohort, "ready")?;
    let drive = async {
        if stalled {
            tokio::select! {r=&mut run=>{r?;bail!("session ended before stall")},_=time::sleep(duration(args.stall_after)?)=>{}}
            emit(
                json!({"type":"stall_begin","client":client,"cohort":cohort,"timestamp_unix_us":unix_us()?}),
            )?;
            stats(&connection, client, cohort, "stall_begin")?;
            // Keep the same pinned session future alive WITHOUT polling it.
            // Quinn drivers keep running, but MoQT cannot drain receive buffers.
            let stall_end = Instant::now() + duration(args.stall_for)?;
            let mut sampling = time::interval(Duration::from_millis(250));
            loop {
                tokio::select! {biased;_=time::sleep_until(stall_end)=>break,_=sampling.tick()=>stats(&connection,client,cohort,"stalled")?}
            }
            stats(&connection, client, cohort, "stall_end")?;
            emit(
                json!({"type":"stall_end","client":client,"cohort":cohort,"timestamp_unix_us":unix_us()?}),
            )?;
        }
        (&mut run).await?;
        bail!("subscriber session ended early")
    };
    tokio::select! {
        r=drive=>r?,
        r=receive(reader,client,cohort)=>r?,
        r=subscription.closed()=>{r?;bail!("subscription ended early")},
        _=time::sleep(duration(args.common.duration)?)=>{},
    }
    stats(&connection, client, cohort, "complete")?;
    emit(
        json!({"type":"complete","role":"subscriber","client":client,"cohort":cohort,"timestamp_unix_us":unix_us()?}),
    )?;
    connection.close(0u32.into(), b"experiment complete");
    Ok(())
}
#[tokio::main]
async fn main() -> Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env().unwrap_or_else(|_| "warn".into()),
        )
        .with_writer(io::stderr)
        .init();
    match Cli::parse().command {
        Command::Publish(args) => publish(args).await,
        Command::Subscribe(args) => {
            ensure!(
                args.clients > 0 && args.stall_clients <= args.clients,
                "invalid client counts"
            );
            duration(args.common.duration)?;
            duration(args.stall_after)?;
            duration(args.stall_for)?;
            let mut tasks = FuturesUnordered::new();
            for index in 0..args.clients {
                let a = args.clone();
                tasks.push(async move { (index, subscriber(a, index).await) });
            }
            let mut errors = 0;
            while let Some((index, result)) = tasks.next().await {
                if let Err(error) = result {
                    errors += 1;
                    emit(
                        json!({"type":"client_error","client":args.client_offset+index,"cohort":if index<args.stall_clients {"stalled"} else {"healthy"},"error":format!("{error:#}"),"timestamp_unix_us":unix_us()?}),
                    )?;
                }
            }
            ensure!(errors == 0, "{errors} client(s) failed");
            Ok(())
        }
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn payload_roundtrip_and_damage_detection() {
        let original = payload(42, 123456789, 4096).unwrap();
        assert_eq!(parse_payload(&original).unwrap(), (42, 123456789));
        assert!(parse_payload(&original[..4095]).is_err());
        let mut damaged = original.to_vec();
        damaged[150] ^= 1;
        assert!(parse_payload(&damaged).is_err());
        damaged = original.to_vec();
        damaged[0] = 0;
        assert!(parse_payload(&damaged).is_err());
        assert!(parse_payload(&[]).is_err());
        assert!(payload(0, 0, 31).is_err());
    }
}
