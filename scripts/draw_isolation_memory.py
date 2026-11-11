#!/usr/bin/env python3
"""Memory ownership figure for the scoped fixed-budget relay."""
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':11})
fig,ax=plt.subplots(figsize=(10,7.1));fig.patch.set_facecolor('white');ax.set(xlim=(0,10),ylim=(0,7.1));ax.axis('off')
def box(x,y,w,h,title,body,color):
 ax.add_patch(FancyBboxPatch((x,y),w,h,boxstyle='round,pad=0.10',facecolor=color,edgecolor='#45566a',linewidth=1))
 ax.text(x+.16,y+h-.18,title,ha='left',va='top',weight='bold',fontsize=12)
 ax.text(x+.16,y+h-.57,body,ha='left',va='top',fontsize=10.4,linespacing=1.45)
def arrow(a,b):ax.annotate('',xy=b,xytext=a,arrowprops={'arrowstyle':'->','color':'#45566a','lw':1.5})
ax.text(0,6.95,'Where the relay holds media',weight='bold',fontsize=17,va='top')
ax.text(0,6.52,'Example settings used in the fixed-budget experiments',fontsize=11,color='#45566a')
box(.1,4.4,3.6,1.55,'Publisher (separate process)','Generates timestamped Objects.\nNo original video file is loaded\ninto relay memory.','#f1f3f5')
box(4.3,4.25,5.4,1.9,'Shared payload store — relay-wide','One stored payload can serve many connections.\nEach subgroup reserves 512 KiB; payload cannot\nexceed that size. Shared pool cap: 8 MiB.\nA group stays charged until its last reader releases it.','#e4eef9')
arrow((3.8,5.15),(4.2,5.15))
box(.1,1.95,5.2,1.8,'Application references — per session','Each subscribed track reserves one cache slot.\nEach active forwarding task reserves another slot.\nAll tracks share a 2 MiB session reservation cap.\nOverflow ends the affected subscription.','#e4f3ec')
box(5.9,1.95,3.8,1.8,'QUIC buffers — per connection','Bytes waiting to be sent or ACKed.\n10 MB outstanding-stream window\n(separate transport accounting).\nNot covered by our payload cap.','#fff0dc')
arrow((5.9,4.15),(3.1,3.85));ax.text(3.65,3.98,'shared references',fontsize=9.5,color='#45566a')
arrow((5.4,2.85),(5.8,2.85))
ax.text(5.6,3.30,'DRR',fontsize=9.5,ha='center',color='#45566a')
box(.1,.35,9.6,1.05,'Other memory — outside these limits','Object/stream metadata, allocator overhead and OS socket buffers remain separate.\nThe 2 MiB cap bounds admitted payload references, not total memory per connection or RSS.','#f1f3f5')
arrow((7.8,1.85),(7.8,1.50))
ax.text(.12,.04,'Shared storage is counted once globally; per-session reservations deliberately overcount shared references.',fontsize=9.3,color='#45566a')
fig.tight_layout(pad=.4)
out=Path(__file__).resolve().parents[1]/'docs/figures/isolation-memory-regions.png';fig.savefig(out,dpi=200,bbox_inches='tight');print(out)
