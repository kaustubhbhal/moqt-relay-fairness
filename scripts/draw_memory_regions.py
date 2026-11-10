#!/usr/bin/env python3
"""Draw the source-audited memory ownership model; no measured sizes inferred."""
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

fig,ax=plt.subplots(figsize=(12,10))
ax.set(xlim=(0,12),ylim=(0,10));ax.axis('off')
blue='#e7f0f8'; peach='#fff0df'; grey='#eeeeee'; edge='#38516a'
def box(x,y,w,h,title,body,color,size=12):
 ax.add_patch(FancyBboxPatch((x,y),w,h,boxstyle='round,pad=0.08',linewidth=1.1,edgecolor=edge,facecolor=color))
 ax.text(x+.16,y+h-.17,title,fontsize=13,fontweight='bold',va='top')
 ax.text(x+.16,y+h-.40,body,fontsize=size,va='top',linespacing=1.18)
def arrow(a,b,label=None,dashed=False):
 ax.add_patch(FancyArrowPatch(a,b,arrowstyle='-|>',mutation_scale=14,linewidth=1.2,color=edge,linestyle='--' if dashed else '-'))
 if label:ax.text((a[0]+b[0])/2+.12,(a[1]+b[1])/2,label,fontsize=10,va='center')
ax.text(6,9.85,'Where a stalled subscriber can retain memory',ha='center',va='top',fontsize=19,fontweight='bold')
box(.3,8.75,11.4,.65,'Publisher process (outside relay RSS)','Synthetic Objects generated live; no original media file is loaded in the relay.',grey,12)
arrow((6,8.68),(6,8.38))
box(.3,7.55,11.4,.75,'Relay ingress: per upstream QUIC connection','Receive / reassembly buffers feed the shared media store; count once for this upstream connection.',grey,12)
arrow((6,7.47),(6,7.17))
box(.3,6.15,11.4,.94,'Shared track / subgroup / Object store','Reference-counted payload chunks and Object lists. A slow reader can keep old groups alive.\nCount each unique payload allocation once, even when many downstreams reference it.',blue,12)
arrow((3,6.07),(3,5.66),'references',True);arrow((9,6.07),(9,5.66),'references',True)
for x,label in [(.3,'A'),(6.3,'B ... N')]:
 box(x,4.32,5.4,1.25,f'Connection {label}: application state',
     'Per-subscription readers, tasks, header buffers.\n128 active subgroup jobs / subscription;\n1,024 FIN-ACK waiters in the patched relay.\nThese are count limits, not payload-byte limits.',peach,11.8)
 arrow((x+2.7,4.24),(x+2.7,3.89))
 box(x,2.14,5.4,1.67,'Per-connection QUIC transport memory',
     'Stream send buffers contain BOTH:\n  - data staged but not yet sent\n  - sent data retained for ACK / retransmission\nSend-window accounting: 10,000,000 bytes.\nPlus packet/range metadata, control receive\nbuffers, TLS state and allocation overhead.',peach,11.8)
 arrow((x+2.7,2.06),(x+2.7,1.73))
box(.3,.82,11.4,.83,'Shared UDP endpoint and kernel socket queues','Packet staging and OS socket buffers serve many connections. Kernel buffers are outside process RSS.\nThe 64 KiB token-bucket burst is a traffic allowance, not a 64 KiB payload queue.',grey,12)
ax.text(.3,.55,'Total maximum for one connection: NOT established. Shared retention + transport + metadata must be accounted for.',fontsize=12,fontweight='bold',va='top')
ax.text(.3,.23,'10 MB is a configured stream-data accounting window, not a proven physical-memory ceiling. Boxes are not to scale.',fontsize=11,va='top')
fig.tight_layout(pad=.5)
out=Path('docs/figures/memory-regions.png');out.parent.mkdir(parents=True,exist_ok=True)
fig.savefig(out,dpi=200,facecolor='white');print(out)
