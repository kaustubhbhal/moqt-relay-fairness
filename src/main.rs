// SPDX-FileCopyrightText: 2026 MoQT Relay Fairness project contributors
// SPDX-License-Identifier: MIT
use anyhow::{bail, ensure, Context, Result};
use bytes::Bytes;
use clap::{Args, Parser, Subcommand};
use futures::{stream::FuturesUnordered, FutureExt, StreamExt};
use moq_transport::{
    coding::{KeyValuePairs, TrackNamespace},
    serve::{ServeError, Track, TrackReader, TrackReaderMode},
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
    /// Number of tracks published on this single QUIC session.
    #[arg(long, default_value_t = 1)]
    tracks: usize,
    /// Per-track rates; when omitted every track uses --bitrate.
    #[arg(long, value_delimiter = ',')]
    track_bitrates: Vec<u64>,
    #[arg(long, value_delimiter = ',')]
    track_priorities: Vec<u8>,
}
#[derive(Args, Clone)]
struct SubscribeArgs {
    #[command(flatten)]
    common: Common,
    #[arg(long, default_value_t = 1)]
    clients: usize,
    /// Total tracks at the publisher. Ordinary clients request the first one.
    #[arg(long, default_value_t = 1)]
    tracks: usize,
    /// Client IDs below this value request every track on one QUIC session.
    #[arg(long, default_value_t = 0)]
    extra_track_clients: usize,
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
    /// Record a received TOO_FAR_BEHIND as an outcome, retaining the full run duration.
    #[arg(long)]
    allow_policy_termination: bool,
    /// Permit stale media abandonment through the standard SUBSCRIBE parameter.
    #[arg(long)]
    delivery_timeout_ms: Option<u64>,
    /// Continue on an explicit data-stream DELIVERY_TIMEOUT reset (patched build).
    #[arg(long)]
    allow_subgroup_reset: bool,
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
fn track_name(total: usize, index: usize) -> String {
    if total == 1 {
        "video".to_string()
    } else {
        format!("track-{index}")
    }
}
fn requested_tracks(total: usize, extra_clients: usize, client: usize) -> usize {
    if client < extra_clients {
        total
    } else {
        1
    }
}
async fn publish(args: PublishArgs) -> Result<()> {
    ensure!(
        args.fps > 0 && args.group_frames > 0 && (1..=16).contains(&args.tracks),
        "fps/group-frames must be positive and tracks must be 1..=16"
    );
    ensure!(
        args.track_bitrates.is_empty() || args.track_bitrates.len() == args.tracks,
        "track-bitrates must have one entry per track"
    );
    ensure!(
        args.track_priorities.is_empty() || args.track_priorities.len() == args.tracks,
        "track-priorities must have one entry per track"
    );
    let denominator = args.fps.checked_mul(8).context("fps overflow")?;
    let mut sizes = Vec::new();
    for i in 0..args.tracks {
        let rate = args.track_bitrates.get(i).copied().unwrap_or(args.bitrate);
        let size: usize = (rate / denominator).try_into()?;
        ensure!(
            (HEADER..=16 * 1024 * 1024).contains(&size),
            "object size must be 32 bytes to 16 MiB"
        );
        sizes.push(size);
    }
    let measurement = duration(args.common.duration)?;
    let Connected {
        _endpoint,
        connection,
        session,
        mut publisher,
        ..
    } = time::timeout(Duration::from_secs(15), connect(&args.common, None)).await??;
    emit(json!({"type":"connection","role":"publisher","timestamp_unix_us":unix_us()?}))?;
    let run = session.run();
    tokio::pin!(run);
    let mut writers = Vec::new();
    let mut forwards = FuturesUnordered::new();
    for i in 0..args.tracks {
        let name = track_name(args.tracks, i);
        let (writer, reader) = Track::new(
            TrackNamespace::from_utf8_path(&args.common.namespace),
            name.clone(),
        )
        .produce();
        let mut published = publisher.publish(reader, KeyValuePairs::default()).await?;
        tokio::select! {
            r=published.ok()=>r?,
            r=&mut run=>{r?;bail!("session ended during publish setup")},
            _=time::sleep(Duration::from_secs(15))=>bail!("publish acknowledgement timed out"),
        }
        emit(json!({"type":"track_ready","role":"publisher","track":name,
            "track_index":i,"timestamp_unix_us":unix_us()?}))?;
        writers.push(writer.subgroups()?);
        forwards.push(async move { published.serve().await });
    }
    emit(
        json!({"type":"ready","role":"publisher","publish_mode":"direct_publish",
        "timestamp_unix_us":unix_us()?,"duration":args.common.duration,"bitrate":args.bitrate,
        "actual_bitrate":sizes[0] as u64*denominator,"aggregate_bitrate":sizes.iter().sum::<usize>() as u64*denominator,
        "fps":args.fps,"group_frames":args.group_frames,"object_bytes":sizes[0],
        "tracks":args.tracks,"track_object_bytes":sizes,"track_priorities":args.track_priorities}),
    )?;
    let generate = async {
        let mut ticker = time::interval(Duration::from_secs_f64(1.0 / args.fps as f64));
        ticker.set_missed_tick_behavior(time::MissedTickBehavior::Skip);
        let end = Instant::now() + measurement;
        let mut groups = (0..args.tracks).map(|_| None).collect::<Vec<_>>();
        let mut seq = 0u64;
        loop {
            tokio::select! { biased; _=time::sleep_until(end)=>break, _=ticker.tick()=>{} }
            for i in 0..args.tracks {
                if seq.is_multiple_of(args.group_frames) {
                    groups[i] = Some(
                        writers[i].append(args.track_priorities.get(i).copied().unwrap_or(128))?,
                    );
                }
                let sent = unix_us()?;
                groups[i]
                    .as_mut()
                    .context("missing subgroup")?
                    .write(payload(seq, sent, sizes[i])?)?;
                emit(
                    json!({"type":"published","track":track_name(args.tracks,i),"track_index":i,
                    "seq":seq,"bytes":sizes[i],"sent_unix_us":sent}),
                )?;
            }
            seq += 1;
        }
        emit(
            json!({"type":"complete","role":"publisher","objects":seq*args.tracks as u64,
            "objects_per_track":seq,"timestamp_unix_us":unix_us()?}),
        )?;
        Ok::<_, anyhow::Error>(())
    };
    tokio::select! {
        r=generate=>r?,
        r=forwards.next()=>{r.context("no publisher forwarders")??;bail!("publisher forwarding ended early")},
        r=&mut run=>{r?;bail!("publisher session ended early")},
    }
    connection.close(0u32.into(), b"experiment complete");
    Ok(())
}
async fn receive(
    reader: TrackReader,
    client: usize,
    cohort: &str,
    allow_reset: bool,
    track: &str,
) -> Result<()> {
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
                    loop {
                        let bytes = match subgroup.read_next().await {
                            Ok(Some(bytes)) => bytes,
                            Ok(None) => break,
                            Err(error) if allow_reset && delivery_reset(&error) => {
                                emit(json!({"type":"subgroup_reset","client":client,"cohort":cohort,"track":track,
                                    "group_id":subgroup.group_id,"subgroup_id":subgroup.subgroup_id,
                                    "code":2,"timestamp_unix_us":unix_us()?}))?;
                                break;
                            },
                            Err(error) => return Err(error.into()),
                        };
                        let received=unix_us()?;
                        let (seq,sent)=parse_payload(&bytes)?;
                        let latency=(received as i128-sent as i128) as f64/1000.0;
                        emit(json!({"type":"object","client":client,"cohort":cohort,"track":track,"seq":seq,"bytes":bytes.len(),"sent_unix_us":sent,"received_unix_us":received,"latency_ms":latency}))?;
                    }
                    Ok::<_,anyhow::Error>(())
                });
            },
            result=tasks.next(),if !tasks.is_empty()=>{if let Some(r)=result {r?;}},
        }
    }
}
async fn subscriber(args: SubscribeArgs, index: usize) -> Result<()> {
    if args.tracks > 1 {
        return subscriber_multitrack(args, index).await;
    }
    ensure!(
        !args.allow_subgroup_reset || cfg!(feature = "live-resync"),
        "subgroup resets require the patched live-resync client build"
    );
    ensure!(
        args.delivery_timeout_ms != Some(0),
        "delivery timeout must be positive"
    );
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
    let mut params = KeyValuePairs::default();
    if let Some(ms) = args.delivery_timeout_ms {
        params.set_intvalue(0x02, ms);
    }
    let subscription = tokio::select! {
        r=subscriber.subscribe_open_with_params(writer, params)=>r?,
        r=&mut run=>{r?;bail!("session ended during subscribe setup")},
        _=time::sleep(Duration::from_secs(15))=>bail!("subscribe acknowledgement timed out"),
    };
    let connection_id = connection.stable_id();
    let subscription_id = subscription.id;
    emit(
        json!({"type":"ready","role":"subscriber","client":client,"cohort":cohort,"timestamp_unix_us":unix_us()?,"duration":args.common.duration,"stall_after":args.stall_after,"stall_for":args.stall_for,"receive_window":args.receive_window,"stream_receive_window":args.stream_receive_window,"max_uni_streams":args.max_uni_streams,"connection_id":connection_id,"subscription_id":subscription_id,"delivery_timeout_ms":args.delivery_timeout_ms}),
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
    let measurement_end = Instant::now() + duration(args.common.duration)?;
    let mut terminal_deadline = measurement_end;
    let mut delivery_error = None;
    let mut termination_code = None;
    let receiver = receive(reader, client, cohort, args.allow_subgroup_reset, "video");
    tokio::pin!(receiver);
    tokio::pin!(drive);
    loop {
        tokio::select! {
            biased;
            result=subscription.closed()=>{
                if let Some(code) = policy_termination_code(&result).filter(|_| args.allow_policy_termination) {
                    // Do not let a simultaneously ready terminal response hide
                    // an already-available corrupt/truncated media result.
                    if delivery_error.is_none() {
                        if let Some(result) = receiver.as_mut().now_or_never() {
                            let message = checked_terminal_read(result)?;
                            emit(json!({"type":"delivery_error","client":client,"cohort":cohort,
                                "error":message,"timestamp_unix_us":unix_us()?}))?;
                            delivery_error = Some(message);
                        }
                    }
                    termination_code = Some(code);
                    emit(json!({"type":"subscription_terminated","client":client,"cohort":cohort,
                        "status_code":code,"reason":"too_far_behind","timestamp_unix_us":unix_us()?,
                        "preceding_delivery_error":delivery_error}))?;
                    // A killed subscription receives zero bytes for the rest of the
                    // scheduled run. Do not shrink its throughput denominator.
                    time::sleep_until(measurement_end).await;
                    break;
                }
                result.context("subscription ended without an allowed terminal status")?;
                bail!("subscription ended early");
            },
            result=&mut drive=>{result?;bail!("session driver ended unexpectedly")},
            result=&mut receiver,if delivery_error.is_none()=>{
                let error = result.err().unwrap_or_else(|| anyhow::anyhow!("media reader ended early"));
                if !args.allow_policy_termination || !expected_terminal_read_error(&error) {
                    return Err(error);
                }
                emit(json!({"type":"delivery_error","client":client,"cohort":cohort,
                    "error":format!("{error:#}"),"timestamp_unix_us":unix_us()?}))?;
                delivery_error = Some(format!("{error:#}"));
                // A stream reset can precede PUBLISH_DONE. Keep driving control
                // traffic briefly; never guess a policy status from a reset.
                terminal_deadline = Instant::now() + Duration::from_secs(2);
            },
            _=time::sleep_until(terminal_deadline),if delivery_error.is_some()=>{
                bail!("media error without terminal status: {}", delivery_error.as_deref().unwrap_or("unknown"));
            },
            _=time::sleep_until(measurement_end)=>{
                ensure!(delivery_error.is_none(), "media failed near measurement end without terminal status");
                break;
            },
        }
    }
    stats(&connection, client, cohort, "complete")?;
    emit(
        json!({"type":"complete","role":"subscriber","client":client,"cohort":cohort,"timestamp_unix_us":unix_us()?,"termination_code":termination_code,"connection_id":connection.stable_id(),"subscription_id":subscription.id}),
    )?;
    connection.close(0u32.into(), b"experiment complete");
    Ok(())
}

/// One session driver serves every requested track. Per-track termination must
/// not stop the other subscriptions or shorten the session's observation time.
async fn subscriber_multitrack(args: SubscribeArgs, index: usize) -> Result<()> {
    ensure!(
        !args.allow_subgroup_reset || cfg!(feature = "live-resync"),
        "subgroup resets require the patched live-resync client build"
    );
    ensure!(
        args.delivery_timeout_ms != Some(0),
        "delivery timeout must be positive"
    );
    let client = args.client_offset + index;
    let stalled = index < args.stall_clients;
    let cohort = if stalled { "stalled" } else { "healthy" };
    let count = requested_tracks(args.tracks, args.extra_track_clients, client);
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
    let connection_id = connection.stable_id();
    emit(
        json!({"type":"connection","role":"subscriber","client":client,
        "cohort":cohort,"connection_id":connection_id,"timestamp_unix_us":unix_us()?}),
    )?;
    let run = session.run();
    tokio::pin!(run);
    let mut subscriptions = Vec::new();
    let mut ids = Vec::new();
    for i in 0..count {
        let name = track_name(args.tracks, i);
        let (writer, reader) = Track::new(
            TrackNamespace::from_utf8_path(&args.common.namespace),
            name.clone(),
        )
        .produce();
        let mut params = KeyValuePairs::default();
        if let Some(ms) = args.delivery_timeout_ms {
            params.set_intvalue(0x02, ms);
        }
        let subscription = tokio::select! {
            r=subscriber.subscribe_open_with_params(writer,params)=>r?,
            r=&mut run=>{r?;bail!("session ended during subscribe setup")},
            _=time::sleep(Duration::from_secs(15))=>bail!("subscribe acknowledgement timed out"),
        };
        ids.push(subscription.id);
        emit(
            json!({"type":"track_ready","role":"subscriber","client":client,"cohort":cohort,
            "track":name,"subscription_id":subscription.id,"connection_id":connection_id,
            "timestamp_unix_us":unix_us()?}),
        )?;
        subscriptions.push((name, subscription, reader));
    }
    emit(
        json!({"type":"ready","role":"subscriber","client":client,"cohort":cohort,
        "timestamp_unix_us":unix_us()?,"duration":args.common.duration,"stall_after":args.stall_after,
        "stall_for":args.stall_for,"receive_window":args.receive_window,"stream_receive_window":args.stream_receive_window,
        "max_uni_streams":args.max_uni_streams,"connection_id":connection_id,"subscription_id":ids[0],
        "subscription_ids":ids,"tracks":count,"delivery_timeout_ms":args.delivery_timeout_ms}),
    )?;
    stats(&connection, client, cohort, "ready")?;
    let drive = async {
        if stalled {
            tokio::select! {r=&mut run=>{r?;bail!("session ended before stall")},_=time::sleep(duration(args.stall_after)?)=>{}}
            emit(
                json!({"type":"stall_begin","client":client,"cohort":cohort,"timestamp_unix_us":unix_us()?}),
            )?;
            stats(&connection, client, cohort, "stall_begin")?;
            let end = Instant::now() + duration(args.stall_for)?;
            let mut sampling = time::interval(Duration::from_millis(250));
            loop {
                tokio::select! {biased;_=time::sleep_until(end)=>break,_=sampling.tick()=>stats(&connection,client,cohort,"stalled")?}
            }
            stats(&connection, client, cohort, "stall_end")?;
            emit(
                json!({"type":"stall_end","client":client,"cohort":cohort,"timestamp_unix_us":unix_us()?}),
            )?;
        }
        (&mut run).await?;
        bail!("subscriber session ended early")
    };
    tokio::pin!(drive);
    let end = Instant::now() + duration(args.common.duration)?;
    let mut receivers = FuturesUnordered::new();
    for (name, subscription, reader) in subscriptions {
        receivers.push(monitor_track(
            subscription,
            reader,
            client,
            cohort,
            name,
            args.allow_subgroup_reset,
            args.allow_policy_termination,
        ));
    }
    let mut terminated = Vec::new();
    loop {
        tokio::select! {
            biased;
            result=&mut drive=>{result?;bail!("session driver ended unexpectedly")},
            result=receivers.next(),if !receivers.is_empty()=>{
                let (name,code)=result.context("missing receiver result")??;
                terminated.push(json!({"track":name,"status_code":code}));
            },
            _=time::sleep_until(end)=>break,
        }
    }
    stats(&connection, client, cohort, "complete")?;
    emit(
        json!({"type":"complete","role":"subscriber","client":client,"cohort":cohort,
        "timestamp_unix_us":unix_us()?,"connection_id":connection.stable_id(),
        "subscription_id":ids[0],"subscription_ids":ids,"tracks":count,
        "termination_code":if terminated.len()==count {Some(6)} else {None},
        "terminated_tracks":terminated}),
    )?;
    connection.close(0u32.into(), b"experiment complete");
    Ok(())
}

async fn monitor_track(
    subscription: moq_transport::session::Subscribe,
    reader: TrackReader,
    client: usize,
    cohort: &str,
    name: String,
    allow_reset: bool,
    allow_termination: bool,
) -> Result<(String, u64)> {
    let receiver = receive(reader, client, cohort, allow_reset, &name);
    tokio::pin!(receiver);
    let mut delivery_error = None;
    let mut deadline = None;
    loop {
        tokio::select! {
            biased;
            result=subscription.closed()=>{
                if let Some(code)=policy_termination_code(&result).filter(|_|allow_termination) {
                    if delivery_error.is_none() {
                        if let Some(result)=receiver.as_mut().now_or_never() {
                            delivery_error=Some(checked_terminal_read(result)?);
                        }
                    }
                    emit(json!({"type":"subscription_terminated","client":client,"cohort":cohort,
                        "track":name,"subscription_id":subscription.id,"status_code":code,
                        "reason":"too_far_behind","timestamp_unix_us":unix_us()?,
                        "preceding_delivery_error":delivery_error}))?;
                    return Ok((name.clone(),code));
                }
                result.context("subscription ended without allowed terminal status")?;
                bail!("subscription ended early");
            },
            result=&mut receiver,if delivery_error.is_none()=>{
                let error=result.err().unwrap_or_else(||anyhow::anyhow!("media reader ended early"));
                if !allow_termination || !expected_terminal_read_error(&error) {return Err(error);}
                let message=format!("{error:#}");
                emit(json!({"type":"delivery_error","client":client,"cohort":cohort,
                    "track":name,"error":message,"timestamp_unix_us":unix_us()?}))?;
                delivery_error=Some(message);
                deadline=Some(Instant::now()+Duration::from_secs(2));
            },
            _=async {if let Some(end)=deadline {time::sleep_until(end).await;} else {std::future::pending::<()>().await;} }=>{
                bail!("media error without terminal status for {name}");
            },
        }
    }
}

fn policy_termination_code(result: &Result<(), ServeError>) -> Option<u64> {
    match result {
        Err(ServeError::Closed(code))
            if *code == moq_transport::message::PublishDoneCode::TooFarBehind as u64 =>
        {
            Some(*code)
        }
        _ => None,
    }
}
fn delivery_reset(error: &ServeError) -> bool {
    #[cfg(feature = "live-resync")]
    {
        matches!(error, ServeError::Reset(2))
    }
    #[cfg(not(feature = "live-resync"))]
    {
        let _ = error;
        false
    }
}
fn expected_terminal_read_error(error: &anyhow::Error) -> bool {
    #[cfg(feature = "live-resync")]
    if matches!(
        error.downcast_ref::<ServeError>(),
        Some(ServeError::Reset(1))
    ) {
        return true;
    }
    // Only the stock library conflates a partial stream reset with Size. The
    // patched receiver preserves Reset separately, so Size must be fatal there.
    #[cfg(not(feature = "live-resync"))]
    if matches!(error.downcast_ref::<ServeError>(), Some(ServeError::Size)) {
        return true;
    }
    matches!(
        error.downcast_ref::<ServeError>(),
        Some(ServeError::Cancel | ServeError::Closed(6))
    )
}
fn checked_terminal_read(result: Result<()>) -> Result<String> {
    let error = result
        .err()
        .unwrap_or_else(|| anyhow::anyhow!("media reader ended early"));
    if !expected_terminal_read_error(&error) {
        return Err(error);
    }
    Ok(format!("{error:#}"))
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
                args.clients > 0
                    && args.stall_clients <= args.clients
                    && (1..=16).contains(&args.tracks),
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
    fn multiple_tracks_share_a_client_and_have_stable_names() {
        assert_eq!(track_name(1, 0), "video");
        assert_eq!(track_name(4, 3), "track-3");
        assert_eq!(requested_tracks(4, 1, 0), 4);
        assert_eq!(requested_tracks(4, 1, 1), 1);
        assert_eq!(requested_tracks(4, 1, 8), 1);
    }

    #[cfg(feature = "live-resync")]
    #[test]
    fn only_delivery_timeout_resets_are_recoverable() {
        assert!(!expected_terminal_read_error(&anyhow::Error::new(
            ServeError::Size
        )));
        assert!(checked_terminal_read(Err(anyhow::Error::new(ServeError::Size))).is_err());
        assert!(delivery_reset(&ServeError::Reset(2)));
        for error in [
            ServeError::Reset(1),
            ServeError::Reset(0x12),
            ServeError::Size,
            ServeError::Closed(2),
        ] {
            assert!(!delivery_reset(&error));
        }
    }
    #[test]
    fn a_stream_error_is_not_a_policy_termination() {
        assert!(checked_terminal_read(Err(anyhow::anyhow!("payload corrupt"))).is_err());
        assert!(!expected_terminal_read_error(&anyhow::anyhow!(
            "payload corruption"
        )));
        assert!(expected_terminal_read_error(&anyhow::Error::new(
            ServeError::Cancel
        )));
        #[cfg(not(feature = "live-resync"))]
        assert!(expected_terminal_read_error(&anyhow::Error::new(
            ServeError::Size
        )));
        assert!(!expected_terminal_read_error(&anyhow::Error::new(
            ServeError::Closed(1)
        )));
        assert_eq!(
            policy_termination_code(&Err(ServeError::Closed(6))),
            Some(6)
        );
        assert_eq!(policy_termination_code(&Err(ServeError::Cancel)), None);
        assert_eq!(policy_termination_code(&Err(ServeError::Closed(1))), None);
        assert_eq!(policy_termination_code(&Ok(())), None);
    }
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
