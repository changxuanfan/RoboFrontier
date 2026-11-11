"""Generate sampled factory-tour poses; original independent 30-fps station clocks remain intact."""
import argparse, json, math, sys, time
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from robofrontier.factory.playback import FactoryTimeline
from robofrontier.media.motion_recording import digest
from robofrontier.runtime.setup import write_json
ROOT=Path(__file__).resolve().parents[2]
PREP=ROOT/'runs/factory-data/r14'
SCENE=PREP/'scene-v2/scene.xml'

def make_camera(position,target,fov=52):
 position=list(map(float,position))
 # Hide the roof to camera rays only above the ceiling: lighting and shadows remain.
 return dict(position_m=position,target_m=list(map(float,target)),vertical_fov_deg=float(fov),projection='perspective',hidden_layers=[],camera_hidden_layers=['roof'] if position[2]>=7.2 else [])
def desk_camera(c):return make_camera(c['position_m'],c['target_m'],c['vertical_fov_deg'])
def plan(manifest,cameras):
 k=[];visits=[]
 def add(t,c,label):k.append(dict(t=t,camera=c,label=label))
 overview=make_camera([0,-5,54],[0,0,0],58)
 add(0,make_camera([-21,-18,3.4],[-5,-3,1.0],63),'low side opening')
 add(3.5,make_camera([0,-20,3.8],[0,0,1.0],63),'low interior orbit')
 add(8.5,make_camera([24,0,4.6],[-27.5,0,3.05],63),'low interior orbit facing window wall center')
 add(11.5,overview,'factory overhead moving')
 for i,fam in enumerate(('relay','transport','mosaic','dial')):
  start=13.5+(41+9/1.4)*i;ps=[p for p in manifest['placements'] if p['family']==fam]
  def find(level,rank):
   arr=sorted([p for p in ps if p['case_id'].endswith('-d'+str(level))],key=lambda p:p['translation_m'][0]);return arr[rank]
  def top(p,height_scale=1.9):
   a,b,c,d=p['planning_bounds_xy_m'];cx=(a+c)/2;cy=(b+d)/2;span=max(c-a,d-b)
   return make_camera([cx,cy-span*.3,span*height_scale+3],[cx,cy,.7],48)
  p1,p2,p3=find(1,0),find(1,1),find(1,2);p23,p33=find(2,2),find(3,2)
  f=lambda p:desk_camera(cameras[p['case_id']+'--front'])
  side=lambda p:desk_camera(cameras[p['case_id']+'--side'])
  add(start,top(p1),fam+' first top');add(start+0.7,top(p1),fam+' top hold')
  add(start+2,f(p1),fam+' first front');add(start+7,f(p1),fam+' first front hold')
  add(start+8,f(p2),fam+' second front');add(start+11,f(p2),fam+' second front hold')
  add(start+12,f(p3),fam+' third front');add(start+15,f(p3),fam+' third front hold')
  add(start+17,side(p3),fam+' first row third side');add(start+21,side(p3),fam+' first row third side hold')
  add(start+24,side(p23),fam+' second row third side');add(start+28,side(p23),fam+' second row third side hold')
  add(start+31,side(p33),fam+' third row third side');add(start+35,side(p33),fam+' third row third side hold')
  add(start+37,f(p33),fam+' third row third front');add(start+41,f(p33),fam+' third row third front hold')
  add(start+41+4/1.4,overview,fam+' to factory overview')
  for p,offset in ((p1,0),(p2,8),(p3,12),(p3,17),(p23,24),(p33,31)):
   visits.append(dict(case_id=p['case_id'],arrival_s=start+offset))
 add(210.5,overview,'factory closing')
 if not (all(a['t']<b['t'] for a,b in zip(k,k[1:]))):
     raise ValueError("Check failed: all(a['t']<b['t'] for a,b in zip(k,k[1:]))")
 return k,visits

def may_be_visible(camera,placement):
 # Conservative bounding-sphere frustum test; treats edge intersections as visible.
 bounds=placement['planning_bounds_xy_m'];center=np.array([(bounds[0]+bounds[2])/2,(bounds[1]+bounds[3])/2,1.2]);radius=np.linalg.norm([(bounds[2]-bounds[0])/2,(bounds[3]-bounds[1])/2,1.5])+0.4
 pos=np.array(camera['position_m']);forward=np.array(camera['target_m'])-pos;forward=forward/np.linalg.norm(forward)
 right=np.cross(forward,[0,0,1.]);norm=np.linalg.norm(right)
 if norm<1e-8:right=np.array([1.,0.,0.])
 else:right=right/norm
 up=np.cross(right,forward);v=center-pos;depth=float(np.dot(v,forward))
 if depth < -radius:return False
 tanv=math.tan(math.radians(camera['vertical_fov_deg'])/2);tanh=tanv*1.8
 return abs(float(np.dot(v,right))) <= max(0.,depth)*tanh+radius*math.sqrt(1+tanh*tanh) and abs(float(np.dot(v,up))) <= max(0.,depth)*tanv+radius*math.sqrt(1+tanv*tanv)

def camera_at(keys,t):
 if t<=keys[0]['t']:return keys[0]['camera']
 # Hermite splines share velocities at opening waypoints so the pan does not pause.
 if t<=keys[3]['t']:
  opening=keys[:4]
  for j,(a,b) in enumerate(zip(opening,opening[1:])):
   if t<=b['t']:
    dt=b['t']-a['t'];u=(t-a['t'])/dt
    h00=2*u**3-3*u**2+1;h10=u**3-2*u**2+u;h01=-2*u**3+3*u**2;h11=u**3-u**2
    def interp(field):
     v0=np.asarray(a['camera'][field],float);v1=np.asarray(b['camera'][field],float)
     def tangent(before,current,after):
      left=(np.asarray(current['camera'][field],float)-np.asarray(before['camera'][field],float))/(current['t']-before['t'])
      right=(np.asarray(after['camera'][field],float)-np.asarray(current['camera'][field],float))/(after['t']-current['t'])
      mean=(np.asarray(after['camera'][field],float)-np.asarray(before['camera'][field],float))/(after['t']-before['t'])
      return np.where(left*right>0,np.sign(mean)*np.minimum(np.abs(mean),3*np.minimum(np.abs(left),np.abs(right))),0.)
     m0=np.zeros_like(v0) if j==0 else tangent(opening[j-1],a,b)
     m1=np.zeros_like(v1) if j+2>=len(opening) else tangent(a,b,opening[j+2])
     return h00*v0+h10*dt*m0+h01*v1+h11*dt*m1
    return make_camera(interp('position_m'),interp('target_m'),interp('vertical_fov_deg'))
 for a,b in zip(keys,keys[1:]):
  if t<=b['t']:
   q=(t-a['t'])/(b['t']-a['t']);q=q*q*(3-2*q)
   A=a['camera'];B=b['camera'];return make_camera(np.array(A['position_m'])*(1-q)+np.array(B['position_m'])*q,np.array(A['target_m'])*(1-q)+np.array(B['target_m'])*q,A['vertical_fov_deg']*(1-q)+B['vertical_fov_deg']*q)
 return keys[-1]['camera']

def main():
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--duration',type=float,default=210.5);p.add_argument('--preview-fps',type=int,default=5);p.add_argument('--prep',type=Path,default=PREP);p.add_argument('--scene',type=Path);p.add_argument('--cameras',type=Path);p.add_argument('--camera-plan',type=Path,help='Frozen editable camera waypoints; omit for the Legacy tour');p.add_argument('--release',type=Path,required=True,help='Fully combined release with resolved input paths');args=p.parse_args();prep=args.prep.resolve();scene=args.scene or prep/'scene/scene.xml'
 if not math.isfinite(args.duration) or args.duration<=0:raise ValueError('Positive finite duration required')
 if args.preview_fps not in (1,2,3,5,6,10,15,30):raise ValueError('Preview fps must divide 30')
 output=args.output;output.mkdir(parents=True,exist_ok=False)
 release=json.loads(args.release.read_text());
 write_json(output/'release.json',release)
 manifest=json.loads((scene.parent/'manifest.json').read_text());cameras={x['id']:x for x in json.loads((args.cameras or prep/'cameras.json').read_text())};keys,visits=plan(manifest,cameras);write_json(output/'camera-plan.json',keys);placements={p['case_id']:p for p in manifest['placements']}
 if args.camera_plan:
  from robofrontier.factory.editorial import camera_plan
  keys=camera_plan(args.camera_plan)
  if args.duration>keys[-1]['t']+1e-8:raise ValueError('Requested video exceeds the editorial camera timeline')
  write_json(output/'camera-plan.json',keys)
 timeline=FactoryTimeline(scene,release,loop=False)
 try:
  model,data=timeline.play.model,timeline.play.data;names=timeline.play.manifest['workstation_names']
  gids=np.array(sorted({model.geom(target).id for track in timeline.tracks for target in names[track.spec['id']]['geom_names'].values()}),dtype=np.int32);bids=np.unique(model.geom_bodyid[gids])
  appearance=sorted({model.geom(names[track.spec['id']]['geom_names'][name]).id for track in timeline.tracks for event in track._event_list for name in event['geoms'] if name in names[track.spec['id']]['geom_names']})
  frames=[];step=30//args.preview_fps;count=math.ceil(args.duration*args.preview_fps);started=time.monotonic();station_starts={};reset_events=[]
  with (output/'frames.jsonl').open('x') as trace:
   for i in range(count):
    frame=i*step;camera=camera_at(keys,i/args.preview_fps)
    if frame and camera['position_m'][2]<20:
     for track in timeline.tracks:
      ident=track.spec['id'];local=frame-station_starts.get(ident,0)
      # For clips shorter than 15 seconds, wait for completion to avoid resetting forever.
      threshold=track.frame_count-450 if track.frame_count>450 else track.frame_count
      if local>=threshold and not may_be_visible(camera,placements[ident]):
       reset_events.append(dict(case_id=ident,frame_30=frame,time_s=i/args.preview_fps,remaining_s=max(0,(track.frame_count-local)/30)))
       station_starts[ident]=frame
    sample=timeline.at(frame,station_starts);trace.write(json.dumps(sample,separators=(',',':'))+'\n');file=output/f'pose-{i:06d}.npz'
    np.savez_compressed(file,geom_ids=gids,position=data.geom_xpos[gids].astype(np.float32),rotation=data.geom_xmat[gids].reshape(-1,3,3).astype(np.float32),rgba=model.geom_rgba[gids],body_ids=bids,body_position=data.xpos[bids].astype(np.float32),body_rotation=data.xmat[bids].reshape(-1,3,3).astype(np.float32))
    frames.append(dict(file=file.name,sha256=digest(file),camera=camera))
    if i%25==0:print('pose',i,'/',count,'seconds',round(time.monotonic()-started,1),flush=True)
  write_json(output/'reset-events.json',reset_events);print('OFFSCREEN RESETS',len(reset_events),flush=True)
  result=dict(schema='robofrontier.factory-animation.v1',source_scene_sha256=digest(scene),fps=30,frames=frames,loop=False,stations=len(timeline.tracks),release_sha256=digest(output/'release.json'),source_trace_sha256=digest(output/'frames.jsonl'),appearance_geom_ids=appearance,camera_motion=dict(mode='promo-preview',duration_s=args.duration,preview_fps=args.preview_fps),physics_steps=0,scope='Sampled exact station state for preview')
  write_json(output/'animation.json',result);print('DONE',count,'stations',len(timeline.tracks),flush=True)
 finally:timeline.close()
if __name__=='__main__':main()
