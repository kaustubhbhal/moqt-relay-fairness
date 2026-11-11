#!/usr/bin/env python3
"""Regenerate PR2 figures from accepted isolation experiment summaries."""
import json
from pathlib import Path
import statistics as st
from isolation_experiment import read_events
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'results/isolation/2026-11-10'
OUT=ROOT/'docs/figures'
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':11,'axes.spines.top':False,'axes.spines.right':False})
colors=['#667c91','#16836b']
def load(suite):return json.loads((DATA/suite/'summary.json').read_text())
def group(suite,policy):return [x for x in load(suite) if x['policy']==policy]
def save(fig,name):
 fig.savefig(OUT/name,dpi=210,bbox_inches='tight',facecolor='white');plt.close(fig)
def bars(ax,series,labels,ylabel,title):
 for i,values in enumerate(series):
  ax.bar(i,st.median(values),color=colors[i],width=.54,alpha=.85)
  ax.scatter(i+np.linspace(-.10,.10,len(values)),values,color='#182b3a',s=25,zorder=5)
 ax.set(xticks=range(len(labels)),xticklabels=labels,ylabel=ylabel,title=title)
 ax.grid(axis='y',alpha=.18);ax.set_axisbelow(True)
fig,axs=plt.subplots(1,2,figsize=(10,4.3),gridspec_kw={'width_ratios':[2.2,1]},layout='constrained')
for j,p in enumerate(['baseline','drr']):
 runs=group('bandwidth',p)
 for i in range(4):
  values=[r['clients'][i]['throughput_mbps'] for r in runs];x=i+(j-.5)*.34
  axs[0].bar(x,st.median(values),width=.32,color=colors[j],label=['FIFO','DRR'][j] if i==0 else None,alpha=.85)
  axs[0].scatter(x+np.linspace(-.055,.055,len(values)),values,color='#182b3a',s=16,zorder=4)
axs[0].axhline(3,ls='--',lw=1,color='#87692c',label='12 Mbit/s ÷ 4 sessions')
axs[0].set(xticks=range(4),xticklabels=['Client 0\n4 tracks','Client 1\n1 track','Client 2\n1 track','Client 3\n1 track'],ylabel='Received payload (Mbit/s)',title='Bandwidth per QUIC session',ylim=(0,8.1))
axs[0].legend(loc='upper right',frameon=False,fontsize=9);axs[0].grid(axis='y',alpha=.18);axs[0].set_axisbelow(True)
bars(axs[1],[[r['jain_session_throughput'] for r in group('bandwidth',p)] for p in ['baseline','drr']],['FIFO','DRR'],"Jain's fairness index",'Sharing under contention')
axs[1].set_ylim(0,1.1)
for i,p in enumerate(['baseline','drr']):axs[1].text(i,st.median(r['jain_session_throughput'] for r in group('bandwidth',p))+.035,f"{st.median(r['jain_session_throughput'] for r in group('bandwidth',p)):.4f}",ha='center')
fig.suptitle('DRR prevents extra tracks from creating extra session shares',fontsize=14,weight='bold')
save(fig,'isolation-bandwidth.png')
fig,axs=plt.subplots(2,2,figsize=(10,7.1),layout='constrained')
for j,p in enumerate(['baseline','bounded']):
 run=DATA/'memory'/f'{p}-r1'
 events=read_events(run/'subscribers.jsonl')
 t0=min(e['timestamp_unix_us'] for e in events if e.get('type')=='ready')
 snaps=read_events(run/'metrics.jsonl')
 times=[];sess=[];glob=[]
 for snap in snaps:
  t=(snap['timestamp_unix_us']-t0)/1e6
  if not 0<=t<=15:continue
  m={a:float(b) for line in snap['text'].splitlines() if line and not line.startswith('#') for a,_,b in [line.rpartition(' ')]}
  times.append(t);sess.append(max([v for k,v in m.items() if k.startswith('moq_relay_session_reserved_bytes{')] or [0])/1048576);glob.append(m.get('moq_relay_global_reserved_bytes',0)/1048576)
 for ax,vals in zip(axs[0],[sess,glob]):ax.step(times,vals,where='post',label=['No session cap','2 MiB session cap'][j],color=colors[j],lw=2)
for ax in axs[0]:
 ax.axvspan(3,9,color='#e7d8ba',alpha=.35,label='Client paused');ax.set(xlabel='Seconds since subscribers ready',ylabel='Reserved payload (MiB)',xlim=(0,15));ax.grid(alpha=.18);ax.set_axisbelow(True)
axs[0,0].axhline(2,color='#87692c',ls='--',lw=1);axs[0,0].set(title='Largest session reservation over time',ylim=(0,4.5))
axs[0,1].set(title='Shared global reservations over time',ylim=(0,4.5))
axs[0,0].legend(frameon=False,fontsize=8.5,loc='upper right')
axs[0,1].text(.03,.92,'8 MiB global cap never reached',transform=axs[0,1].transAxes,fontsize=9)
pol=['baseline','bounded'];labels=['No session cap','2 MiB cap']
bars(axs[1,0],[[r['peak_relay_rss_bytes']/1048576 for r in group('memory',p)] for p in pol],labels,'Peak process memory (MiB)','RSS: measured separately from reservations')
axs[1,0].set_ylim(bottom=0)
bars(axs[1,1],[[r['healthy_mean_mbps'] for r in group('memory',p)] for p in pol],labels,'Payload per healthy client (Mbit/s)','Healthy-client delivery continues')
axs[1,1].set_ylim(0,4.6)
fig.suptitle('The fixed budget limits retention by ending the stalled subscription',fontsize=13.5,weight='bold')
save(fig,'isolation-memory-results.png')
print('Wrote bandwidth and memory result figures.')
