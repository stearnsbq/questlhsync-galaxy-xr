/* Firmware-pinned QVR spot reader. Own camera handles and read locks only. */
#if !defined(__aarch64__) || __SIZEOF_POINTER__ != 8
#error Android arm64 required
#endif
typedef unsigned long usize;
extern int dprintf(int,const char *,...),usleep(unsigned int),getuid(void),atoi(const char *),strcmp(const char *,const char *);
extern void *dlopen(const char *,int),*dlsym(void *,const char *),*memset(void *,int,usize),*memcpy(void *,const void *,usize);
extern char *dlerror(void);
extern char *getenv(const char *);
extern long write(int,const void *,usize);
extern long read(int,void *,usize);
extern int *__errno(void);
extern int getpid(void);
extern int fcntl(int,int,...);
extern void *signal(int,void (*)(int));
extern unsigned int alarm(unsigned int);
struct Poll { int fd; short events,revents; };
extern int poll(struct Poll *,unsigned long,int);
typedef struct { int version; void **ops; } Api;
typedef struct { void *buffer; unsigned int x,y; } HwBuffer;
typedef struct { unsigned int width,height,layers,format; unsigned long usage; unsigned int stride,rfu0; unsigned long rfu1; } HwDesc;
typedef struct { void *data; unsigned int pixelStride,rowStride; } Plane;
typedef struct { unsigned int count; Plane planes[4]; } Planes;
_Static_assert(sizeof(HwDesc)==40 && sizeof(HwBuffer)==16 && sizeof(Planes)==72,"ABI");
static volatile int running=1;
static void stop_signal(int sig){(void)sig;running=0;}
static int sendall(const void *data,usize len) {
    const char *p=data;
    while(len && running) {
        struct Poll item={1,4,0};
        int ready=poll(&item,1,2000);
        if(ready<0 && *__errno()==4)continue;
        if(ready<=0 || !(item.revents&4))return -1;
        long n=write(1,p,len);if(n<0 && *__errno()==4)continue;
        if(n<0 && *__errno()==11)continue;
        if(n<=0)return -1;p+=n;len-=(usize)n;
    }
    return len?-1:0;
}

extern int snprintf(char *,usize,const char *,...);
extern int open(const char *,int,...),close(int),strncmp(const char *,const char *,usize);
struct Timespec {long sec,nsec;};
extern int clock_gettime(int,struct Timespec *);
static unsigned long now_ns(void) {
    struct Timespec t; if(clock_gettime(1,&t))return 0;
    return (unsigned long)t.sec*1000000000UL+(unsigned long)t.nsec;
}
/* QVR sensor stamps use BOOTTIME; daemon clock replies use MONOTONIC.
   Measure the offset per frame so a suspend cannot leave it stale. */
static struct { unsigned long before,boot,after,offset; } clock_sample;
static const char *sensor_time(unsigned long raw,unsigned long *stamp) {
    memset(&clock_sample,0,sizeof(clock_sample));
    for(int attempt=0;attempt<3;attempt++) {
        struct Timespec boot;
        unsigned long a=now_ns();
        clock_sample.before=a;
        if(!a || clock_gettime(7,&boot))return "clock-read";
        unsigned long b=now_ns();
        unsigned long bn=(unsigned long)boot.sec*1000000000UL+(unsigned long)boot.nsec;
        clock_sample.boot=bn;clock_sample.after=b;
        if(b<a || b-a>200000UL)continue;
        unsigned long mid=a+(b-a)/2;
        /* Without accumulated suspend time, BOOTTIME can fall before the
           midpoint while still inside this MONOTONIC sampling bracket.
           Its offset is nonnegative; clamp only that in-bracket estimate. */
        if(bn<a)return "clock-order";
        unsigned long offset=bn>mid ? bn-mid : 0;
        clock_sample.offset=offset;
        if(raw<offset)return "before-clock-origin";
        *stamp=raw-offset;
        if(*stamp>b)return "future-frame";
        if(b-*stamp>1000000000UL)return "stale-frame";
        return 0;
    }
    return "sampling-window";
}
typedef unsigned char u8; typedef unsigned int u32; typedef unsigned long long u64;
#include "factory_map.h"
#define MAXB 48
#define MAXCELL 1600
static struct {unsigned char scratch[640*640],hot[MAXCELL];unsigned short cells[MAXCELL];int lab[MAXCELL];} S;
static int find(int x){while(S.lab[x]!=x){S.lab[x]=S.lab[S.lab[x]];x=S.lab[x];}return x;}
#include "detector.h"
static unsigned char copies[2][640*640];
static unsigned int counts[4],shorts[4],dots[4];
static int means[4],previous[4],before[4];
static unsigned long rawtimes[4],opaque16[4];
static int audit;
static int sensor_stamped;
static unsigned long frametimes[4];
static unsigned long max_exposure_ns;
static const char *capture_dir;
static int file_write(int fd,const void *data,usize size) {
    const unsigned char *p=data;
    while(size) {
        long n=write(fd,p,size);if(n<0 && *__errno()==4)continue;
        if(n<=0)return -1;p+=n;size-=(usize)n;
    }
    return 0;
}
static int save_pair(int group,int sample,int seq,unsigned long sensor,unsigned long arrival,unsigned int exposure) {
    for(int j=0;j<2;j++) {
        char path[512];int len=snprintf(path,sizeof(path),"%s/pair-%03d-cam-%d.pgm",capture_dir,sample,group*2+j);
        if(len<0 || len>=(int)sizeof(path))return -1;
        int file=open(path,0x241,0600);if(file<0)return -1;
        const char header[]="P5\n640 640\n255\n";
        int ok=!file_write(file,header,sizeof(header)-1);
        if(file_write(file,copies[j],640*640))ok=0;
        if(close(file))ok=0;
        if(!ok)return -1;
        dprintf(1,"I saved sample=%d cam=%d seq=%d sensor=%lu arrival=%lu exposure=%u path=%s\n",sample,group*2+j,seq,sensor,arrival,exposure,path);
    }
    return 0;
}
static int analyze(int cam,int seq,unsigned long arrival,int calibrated) {
    unsigned int sum=0;
    for(int i=0;i<640*640;i+=100)sum+=S.scratch[i];
    int mean=(int)(sum*10/4096);
    int hi=previous[cam]>before[cam]?previous[cam]:before[cam];
    int is_short=calibrated ? (opaque16[cam]>0 && opaque16[cam]<=max_exposure_ns) :
        (counts[cam]>=2 && mean*10<hi*6);
    before[cam]=previous[cam];previous[cam]=mean;means[cam]=mean;counts[cam]++;
    int nbl=-1;u64 sx[MAXB],sy[MAXB];u32 np[MAXB];int pk[MAXB];
    if(is_short)shorts[cam]++;
    /* Galaxy XR's normal AE stream does not alternate dark/bright frames.
       Diagnostics must inspect every frame: the controlled station on/off
       capture found real station spots while this legacy short gate stayed zero.
       Calibrated mode uses the firmware-pinned exposure metadata and profile limit. */
    if(is_short || audit || !calibrated) {
        memset(S.hot,0,sizeof(S.hot));
        nbl=blobs(640,640,250,1,0,sx,sy,np,pk);
        int threshold=mean*4/10;if(threshold<64)threshold=64;
        if(threshold<250)nbl=blobs(640,640,threshold,0,nbl,sx,sy,np,pk);
        dots[cam]+=(unsigned int)nbl;
    }
    if(!calibrated && !audit)return 0;
    if(calibrated && !is_short)return 0;
    int bx[MAXB],by[MAXB],kept=0;
    for(int b=0;b<nbl;b++) {
        int x=(int)(sx[b]/np[b]),y=(int)(sy[b]/np[b]);
        if(gxr_factory && gxr_map_blob(cam,&x,&y)) {gxr_map_rejected[cam]++;continue;}
        bx[kept]=x;by[kept]=y;np[kept]=np[b];pk[kept]=pk[b];kept++;
    }
    nbl=kept;
    char line[2400];int len;
    if(audit) {
        struct Timespec boot;clock_gettime(7,&boot);
        unsigned long boot_ns=(unsigned long)boot.sec*1000000000UL+(unsigned long)boot.nsec;
        len=snprintf(line,sizeof(line),"I sample %d %u %lu %lu %lu %lu %d %d",cam,(unsigned int)seq,arrival,boot_ns,rawtimes[cam],opaque16[cam],mean,nbl);
    } else len=snprintf(line,sizeof(line),"F %d %u %lu %d %d",cam,(unsigned int)seq,(sensor_stamped?frametimes[cam]:arrival)/1000,mean,nbl);
    for(int b=0;b<nbl && len<(int)sizeof(line)-80;b++)
        len+=snprintf(line+len,sizeof(line)-(usize)len," %d %d %u %d",bx[b],by[b],np[b],pk[b]);
    line[len++]='\n';return sendall(line,(usize)len);
}
int main(int argc,char **argv) {
    if(argc<2||getuid()!=0)return 2;
    int calibrated=!strcmp(argv[1],"calibrated");
    if(calibrated) {
        const char *limit=getenv("QLHS_MAX_EXPOSURE_NS");
        if(!limit || !*limit)return 2;
        for(const char *p=limit;*p;p++)if(*p<'0'||*p>'9')return 2;
        int parsed=atoi(limit);
        if(parsed<1 || parsed>3000000)return 2;
        max_exposure_ns=(unsigned long)parsed;
        const char *map=getenv("QLHS_FACTORY_MAP");
        if(map && *map) {
            const char *timing=getenv("QLHS_SENSOR_TIME");
            if(!timing || strcmp(timing,"1")){dprintf(2,"E factory sensor timing required\n");return 2;}
            if(gxr_load_map(map)){dprintf(2,"E invalid factory pixel map; capture refused\n");return 2;}
            gxr_factory=1;
            sensor_stamped=1;
        }
    }
    audit=!strcmp(argv[1],"audit");
    int audit_seconds=20;
    int capture=!strcmp(argv[1],"capture");
    if(capture) {
        if(argc!=4||strncmp(argv[2],"/data/local/tmp/qlhs-gxr-cal-",29)||atoi(argv[3])<1||atoi(argv[3])>300)return 2;
        capture_dir=argv[2];
    } else if(audit) {
        if(argc==3)audit_seconds=atoi(argv[2]);
        if((argc!=2 && argc!=3)||audit_seconds<1||audit_seconds>300)return 2;
    } else if(argc!=2||(!calibrated && strcmp(argv[1],"diagnostic")))return 2;
    int flags=fcntl(1,3);if(flags<0||fcntl(1,4,flags|0x800)<0)return 3;
    signal(15,stop_signal);signal(2,stop_signal);signal(13,stop_signal);
    if(audit){signal(14,stop_signal);alarm((unsigned int)audit_seconds);}
    if(capture){signal(14,stop_signal);alarm((unsigned int)atoi(argv[3]));}
    void *lib=dlopen("/vendor/lib64/libqvrcamera_client.qti.so",2),*window=dlopen("libnativewindow.so",2);
    if(!lib||!window){dprintf(2,"Load failed: %s\n",dlerror());return 3;}
    Api *(*factory)(void)=dlsym(lib,"getQvrCameraClientInstance"),*(*dfactory)(void)=dlsym(lib,"getQvrCameraDeviceInstance");
    int (*start)(void *)=dlsym(lib,"_ZN21QVRCameraDeviceClient5StartEv");
    int (*stop)(void *)=dlsym(lib,"_ZN21QVRCameraDeviceClient4StopEv");
    int (*number)(void *,int *)=dlsym(lib,"_ZN21QVRCameraDeviceClient21GetCurrentFrameNumberEPi");
    int (*frame)(void *,int *,int,int,void *)=dlsym(lib,"_ZN21QVRCameraDeviceClient8GetFrameEPi20QVRCAMERA_BLOCK_MODE19QVRCAMERA_DROP_MODEP17qvrcamera_frame_t");
    int (*release)(void *,int)=dlsym(lib,"_ZN21QVRCameraDeviceClient12ReleaseFrameEi");
    int (*hardware)(void *,void *,unsigned int *,HwBuffer **)=dlsym(lib,"_ZN21QVRCameraDeviceClient21FrameToHardwareBufferEP17qvrcamera_frame_tPjPP21_qvrcamera_hwbuffer_t");
    void (*describe)(void *,HwDesc *)=dlsym(window,"AHardwareBuffer_describe");
    int (*lock)(void *,unsigned long,int,const void *,Planes *)=dlsym(window,"AHardwareBuffer_lockPlanes");
    int (*unlock)(void *,int *)=dlsym(window,"AHardwareBuffer_unlock");
    int (*param)(void *,const char *,unsigned int *,char *)=dlsym(lib,"_ZN21QVRCameraDeviceClient8GetParamEPKcPjPc");
    int (*calibration)(void *,int,unsigned int,unsigned int *,void *,void *)=dlsym(lib,"_ZN21QVRCameraDeviceClient23GetFrameCalibrationInfoEijPjP28XrCameraSensorCalibrationQTIP34XrCameraHwFrameBufferInfoOutputQTI");
    if(!factory||!dfactory||!start||!stop||!number||!frame||!release||!hardware||!describe||!lock||!unlock)return 4;
    Api *api=factory(),*devapi=dfactory();if(!api||!devapi||api->version!=9||devapi->version!=10)return 5;
    void *client=((void *(*)(void))api->ops[0])();if(!client){dprintf(2,"Client creation failed\n");return 6;}

    const char *names[]={"tracking","ctrl-tracking"};
    void *devices[2]={0};int started[2]={0},last[2]={-1,-1},errors=0;
    for(int g=0;g<2;g++) {
        devices[g]=((void *(*)(void *,const char *))api->ops[3])(client,names[g]);
        if(!devices[g]){dprintf(2,"E attach failed: %s\n",names[g]);errors++;running=0;break;}
        int r=start(devices[g]);if(r){dprintf(2,"E start %s=%d\n",names[g],r);errors++;running=0;break;}
        started[g]=1;
        if(audit && param) {
            const char *keys[]={"qvrcamdevice_calibration_name","qvrcamdevice_sensor","qvrcamdevice_auto_exposure","qvrcamdevice_ae_toggle_pattern_size"};
            for(unsigned int k=0;k<4;k++) {
                char value[4096]={0};unsigned int size=sizeof(value)-1;
                int status=param(devices[g],keys[k],&size,value);
                value[sizeof(value)-1]=0;
                dprintf(2,"I param %s %s status=%d size=%u value=%s\n",names[g],keys[k],status,size,status?"":value);
            }
        }
    }
    unsigned long heartbeat=now_ns(),seen[2]={heartbeat,heartbeat};
    int inspected[2]={0};
    unsigned long next_save=heartbeat;int sample=0,saved[2]={0};
    while(running) {
        for(int g=0;g<2 && running;g++) {
            int n=-1;if(number(devices[g],&n)||n<0||n==last[g])continue;
            unsigned long data[512];memset(data,0,sizeof(data));
            if(frame(devices[g],&n,0,1,data))continue;
            unsigned long arrival=now_ns(),stamp=arrival;last[g]=n;seen[g]=arrival;
            if(sensor_stamped) {
                const char *reason=sensor_time(data[1],&stamp);
                if(!reason && frametimes[g*2] && stamp<=frametimes[g*2])reason="non-increasing-frame";
                if(reason) {
                    release(devices[g],n);
                    dprintf(2,"E invalid QVR sensor clock; capture refused reason=%s group=%s raw=%lu mono_before=%lu boot=%lu mono_after=%lu offset=%lu previous=%lu\n",
                            reason,names[g],data[1],clock_sample.before,clock_sample.boot,clock_sample.after,clock_sample.offset,frametimes[g*2]);
                    errors++;running=0;break;
                }
            }
            if(audit && !inspected[g] && calibration) {
                inspected[g]=1;unsigned int needed=0;
                int cr=calibration(devices[g],n,0,&needed,0,0);
                dprintf(2,"I calibration_count group=%s result=%d count=%u exposure_control_denied=%u\n",names[g],cr,needed,((unsigned char *)devices[g])[0x123]);
                // This firmware copies at most 2*152 bytes for the v1 output.
                // A NULL hardware-info input is rejected by the library when
                // it cannot obtain dimensions; never invent that pointer ABI.
                if(!cr && needed==2) {
                    unsigned long cal[512]={0};
                    cr=calibration(devices[g],n,needed,&needed,cal,0);
                    dprintf(2,"I calibration_data group=%s result=%d",names[g],cr);
                    if(!cr)for(unsigned int k=0;k<304;k++)dprintf(2,"%s%02x",k?"":" hex=",((unsigned char *)cal)[k]);
                    dprintf(2,"\n");
                }
            }
            unsigned int count=0;HwBuffer *buffers=0;
            int hr=hardware(devices[g],data,&count,&buffers),ok=1;
            if(hr||!buffers||count!=2){dprintf(2,"E unexpected pair %s result=%d count=%u\n",names[g],hr,count);ok=0;}
            else for(unsigned int j=0;j<2;j++) {
                HwDesc desc={0};Planes planes={0};describe(buffers[j].buffer,&desc);
                if(desc.width!=640||desc.height!=640||desc.layers!=1||desc.format!=0x123||desc.stride!=640){ok=0;break;}
                if(lock(buffers[j].buffer,3,-1,0,&planes)){ok=0;break;}
                Plane *p=&planes.planes[0];
                if(planes.count!=1||!p->data||!((p->pixelStride==0&&p->rowStride==0)||(p->pixelStride==1&&p->rowStride==640)))ok=0;
                else memcpy(copies[j],p->data,640*640);
                if(unlock(buffers[j].buffer,0))ok=0;
                if(!ok)break;
            }
            // Always release vendor-owned frames before processing or output.
            if(release(devices[g],n))ok=0;
            if(!ok){dprintf(2,"E buffer layout/lock/release failed for %s\n",names[g]);errors++;running=0;break;}
            if(capture && arrival>=next_save && !saved[g]) {
                if(save_pair(g,sample,n,data[1],arrival,((unsigned int *)data)[4])){errors++;running=0;break;}
                saved[g]=1;
                if(saved[0] && saved[1]){sample++;saved[0]=saved[1]=0;next_save=arrival+2000000000UL;}
            }
            for(int j=0;j<2 && running;j++) {
                // GetFrame copies a 32-bit exposure field to offset 16; the
                // following four bytes are not part of its duration.
                int cam=g*2+j;rawtimes[cam]=data[1];opaque16[cam]=((unsigned int *)data)[4];frametimes[cam]=stamp;
                memcpy(S.scratch,copies[j],640*640);
                if(analyze(cam,n,arrival,calibrated))running=0;
            }
        }
        unsigned long t=now_ns();
        if(t-heartbeat>=1000000000UL) {
            heartbeat=t;
            for(int c=0;c<4;c++) {
                char line[480];int len=snprintf(line,sizeof(line),"I gxr cam=%d frames=%u mean10=%d short_candidates=%u blobs=%u raw_timestamp=%lu opaque16=%lu arrival_ns=%lu mode=%s map_rejected=%u frame_ns=%lu clock=%s\n",c,counts[c],means[c],shorts[c],dots[c],rawtimes[c],opaque16[c],seen[c/2],gxr_factory?"factory-trial":calibrated?"calibrated":"diagnostic",gxr_map_rejected[c],frametimes[c],sensor_stamped?"sensor-monotonic":"arrival-monotonic");
                if(sendall(line,(usize)len))running=0;
            }
            if(t-seen[0]>10000000000UL||t-seen[1]>10000000000UL){dprintf(2,"W no frames for ten seconds; headset may be asleep\n");break;}
        }
        usleep(1000);
    }
    for(int g=0;g<2;g++)if(devices[g]) {
        if(started[g]){int r=stop(devices[g]);dprintf(2,"I stop %s=%d\n",names[g],r);if(r)errors++;}
        ((void (*)(void *))devapi->ops[0])(devices[g]);
    }
    ((void (*)(void *))api->ops[1])(client);
    dprintf(2,"I GXR capture closed errors=%d\n",errors);
    return errors?7:0;
}
