/* Private factory trial: immutable, host-generated 640x640 pixel map per camera.
   No solver changes. Invalid map cells reject observations conservatively. */
#define GXR_MAP_VALUES (4u*640u*640u*2u)
static float gxr_map[GXR_MAP_VALUES];
static int gxr_factory;
static unsigned int gxr_map_rejected[4];

static int gxr_read_exact(int fd,void *data,usize size) {
    unsigned char *p=data;
    while(size) {
        long n=read(fd,p,size);
        if(n<0 && *__errno()==4)continue;
        if(n<=0)return -1;
        p+=n;size-=(usize)n;
    }
    return 0;
}
static int gxr_load_map(const char *path) {
    int fd=open(path,0);if(fd<0)return -1;
    unsigned int header[5];unsigned char extra;
    int ok=!gxr_read_exact(fd,header,sizeof(header));
    if(ok && (strncmp((char *)header,"GXRMAP1",8) || header[2]!=640 || header[3]!=640 || header[4]!=4))ok=0;
    if(ok && gxr_read_exact(fd,gxr_map,sizeof(gxr_map)))ok=0;
    if(ok && read(fd,&extra,1)!=0)ok=0;
    close(fd);
    if(!ok)return -1;
    for(unsigned int i=0;i<GXR_MAP_VALUES;i+=2) {
        float x=gxr_map[i],y=gxr_map[i+1];
        if(x==-1 && y==-1)continue;
        if(!(x>=0 && x<640 && y>=0 && y<640))return -1;
    }
    return 0;
}
static int gxr_map_blob(int cam,int *px,int *py) {
    int x=*px,y=*py;
    if(cam<0 || cam>=4 || x<0 || x>6390 || y<0 || y>6390)return -1;
    int ix=x/10,iy=y/10,dx=x%10,dy=y%10;
    double ox=0,oy=0;
    for(int j=0;j<2;j++)for(int i=0;i<2;i++) {
        int weight=(i?dx:10-dx)*(j?dy:10-dy);
        if(!weight)continue;
        unsigned int idx=((unsigned int)cam*640u*640u+(unsigned int)(iy+j)*640u+(unsigned int)(ix+i))*2u;
        if(idx+1>=GXR_MAP_VALUES || gxr_map[idx]<0 || gxr_map[idx+1]<0)return -1;
        ox+=weight*(double)gxr_map[idx];oy+=weight*(double)gxr_map[idx+1];
    }
    /* Coordinates on the wire are tenths of a pixel. */
    *px=(int)(ox*.1+.5);*py=(int)(oy*.1+.5);
    return (*px>=0 && *px<6400 && *py>=0 && *py<6400)?0:-1;
}
