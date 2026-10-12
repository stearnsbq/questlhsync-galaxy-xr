/* Native factory map preparation using the validated spline and curved-window
   model. No fitting, vendor modifications, or device-specific constants.
   Static musl executable. */
#include <ctype.h>
#include <errno.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define PI 3.14159265358979323846
typedef struct { const char *p, *end; } Span;
typedef struct { Span name, value; int message; } Field;
typedef struct {
    char id[128];
    double focal[2], principal[2], offset[2], k[6], rd, ru;
    double center[3], radius, thickness, index, correction[1000];
    double position[3], q[4], transform[16];
    int present, extrinsics;
} Camera;

static void fail(const char *message) {
    fprintf(stderr, "Factory setup refused: %s\n", message);
    exit(2);
}
static void space(Span *s) {
    while (s->p < s->end) {
        if (isspace((unsigned char)*s->p)) { s->p++; continue; }
        if (*s->p == '#') { while (s->p < s->end && *s->p != '\n') s->p++; continue; }
        break;
    }
}
static Span token(Span *s) {
    space(s);
    const char *start = s->p;
    if (s->p < s->end && *s->p == '"') {
        start = ++s->p;
        while (s->p < s->end && *s->p != '"') {
            if (*s->p == '\\') fail("unsupported escaped profile string");
            s->p++;
        }
        if (s->p == s->end) fail("unterminated profile string");
        Span result = {start, s->p++};
        return result;
    }
    while (s->p < s->end && !isspace((unsigned char)*s->p) &&
           !strchr("{}:#", *s->p)) s->p++;
    if (start == s->p) fail("malformed profile token");
    return (Span){start, s->p};
}
static int equal(Span s, const char *value) {
    return (size_t)(s.end-s.p) == strlen(value) && !memcmp(s.p, value, strlen(value));
}
static int next(Span *s, Field *f) {
    space(s);
    if (s->p == s->end) return 0;
    f->name = token(s);
    space(s);
    if (s->p == s->end) fail("missing field value");
    if (*s->p == ':') {
        s->p++; f->value = token(s); f->message = 0; return 1;
    }
    if (*s->p++ != '{') fail("expected profile message");
    f->message = 1;
    f->value.p = s->p;
    int depth = 1;
    while (s->p < s->end && depth) {
        space(s);
        if (s->p == s->end) break;
        if (*s->p == '"') { (void)token(s); continue; }
        char c = *s->p++;
        if (c == '{' && ++depth > 32) fail("profile nesting too deep");
        if (c == '}') depth--;
    }
    if (depth) fail("unterminated profile message");
    f->value.end = s->p-1;
    return 1;
}
static Span find(Span s, const char *name, int message, int required) {
    Field f; Span result = {0};
    while (next(&s, &f)) if (equal(f.name, name)) {
        if (result.p || f.message != message) fail("duplicate or mistyped calibration field");
        result = f.value;
    }
    if (!result.p && required) fail(name);
    return result;
}
static double number(Span s, const char *name) {
    Span value = find(s, name, 0, 1);
    char buffer[128], *end;
    size_t size = (size_t)(value.end-value.p);
    if (!size || size >= sizeof buffer) fail("invalid numeric field");
    memcpy(buffer, value.p, size); buffer[size] = 0;
    errno = 0;
    double v = strtod(buffer, &end);
    if (errno || *end || !isfinite(v)) fail("non-finite or invalid number");
    return v;
}
static void vector(Span s, const char *name, const char **axes, int n, double *out) {
    Span value = find(s, name, 1, 1);
    for (int i = 0; i < n; i++) out[i] = number(value, axes[i]);
}
static const char *xy[] = {"x", "y"};
static const char *xyz[] = {"x", "y", "z"};
static const char *wxyz[] = {"w", "x", "y", "z"};
static const char *coefficients[] = {"k0", "k1", "k2", "k3", "k4", "k5"};
static double dot(const double *a, const double *b, int n) {
    double v = 0; for (int i = 0; i < n; i++) v += a[i]*b[i]; return v;
}
static void normalize(double *v, int n) {
    double length = sqrt(dot(v, v, n));
    if (!isfinite(length) || length < 1e-15) fail("invalid optical direction");
    for (int i = 0; i < n; i++) v[i] /= length;
}
static double distorted(const Camera *c, double theta) {
    int segment = (int)(theta/(PI/6));
    if (segment > 2) segment = 2;
    double u = theta/(PI/6)-segment;
    double a = segment ? c->k[2*segment-2] : 0;
    double da = segment ? c->k[2*segment-1] : 0;
    double b = c->k[2*segment], db = c->k[2*segment+1];
    return theta*(1+a+u*(da+u*((3*(b-a)-2*da-db)+u*(2*(a-b)+da+db))));
}
static void lookup(Camera *c) {
    double distance = sqrt(dot(c->center, c->center, 3));
    if (!(c->radius > 0 && c->thickness >= 0 && c->thickness < c->radius &&
          c->index >= 1 && distance > 0 && distance <= c->radius-c->thickness/2))
        fail("invalid curved window");
    for (int i = 0; i < 1000; i++) {
        double cosine = -1.+2.*i/999., sine = sqrt(fmax(0, 1-cosine*cosine));
        double d[2] = {cosine, sine}, o[2] = {0, 0};
        for (int surface = 0; surface < 2; surface++) {
            double radius = c->radius+(surface ? .5 : -.5)*c->thickness;
            double eta = surface ? c->index : 1/c->index;
            double delta[2] = {o[0]+distance, o[1]}, prod = dot(delta, d, 2);
            double disc = prod*prod-dot(delta, delta, 2)+radius*radius;
            if (disc < 0) fail("window intersection");
            double travel = -prod+sqrt(disc);
            for (int j = 0; j < 2; j++) o[j] += travel*d[j];
            double normal[2] = {(o[0]+distance)/radius, o[1]/radius};
            double incidence = dot(normal, d, 2), transmitted = 1-eta*eta*(1-incidence*incidence);
            if (transmitted < 0) fail("window total internal reflection");
            for (int j = 0; j < 2; j++) d[j] = eta*d[j]+(sqrt(transmitted)-eta*incidence)*normal[j];
            normalize(d, 2);
        }
        double travel = (1-o[0])/d[0];
        double amount = cosine-sine*(o[0]+travel*d[0])/(o[1]+travel*d[1]);
        if (i == 0 || i == 999) amount = 0;
        if (!isfinite(amount)) fail("non-finite window lookup");
        c->correction[i] = amount;
    }
}
static void read_cameras(Span profile, Camera *cameras) {
    Span scan = profile; Field f;
    while (next(&scan, &f)) if (equal(f.name, "cameras") && f.message) {
        Span logical = find(f.value, "logical_camera_info", 1, 0);
        if (!logical.p) continue;
        Span name = find(logical, "logical_camera_id", 0, 1);
        int group = equal(name, "tracking") ? 0 : equal(name, "ctrl-tracking") ? 2 : -1;
        if (group < 0) continue;
        Span physical = find(logical, "physical_camera_id", 0, 1);
        int index = equal(physical, "0") ? 0 : equal(physical, "1") ? 1 : -1;
        if (index < 0) fail("unknown tracking camera index");
        Camera *c = &cameras[group+index];
        if (c->present++) fail("duplicate tracking camera");
        Span id = find(f.value, "camera_id", 0, 1);
        if ((size_t)(id.end-id.p) >= sizeof c->id || id.end == id.p) fail("invalid camera ID");
        memcpy(c->id, id.p, (size_t)(id.end-id.p));
        if (number(f.value, "calibrated_width") != 640 || number(f.value, "calibrated_height") != 640 ||
            number(f.value, "rolling_shutter_readout_time_nanoseconds") != 0 ||
            !equal(find(f.value, "camera_timebase_trust_level", 0, 1), "TRUSTED_AS_BOOTTIME"))
            fail("unsupported sensor geometry or timing");
        vector(f.value, "calibrated_focal_length", xy, 2, c->focal);
        vector(f.value, "calibrated_principal_point", xy, 2, c->principal);
        vector(f.value, "distortion_offset", xy, 2, c->offset);
        vector(f.value, "distortion_fisheye_spline3", coefficients, 6, c->k);
        c->rd = number(f.value, "max_valid_distorted_radius");
        c->ru = number(f.value, "max_valid_undistorted_radius");
        if (!(c->focal[0] > 0 && c->focal[1] > 0 && c->rd > 0 && c->ru > 0)) fail("invalid optics bounds");
        Span window = find(find(f.value, "layered_distortion", 1, 1), "curved_window", 1, 1);
        vector(window, "center", xyz, 3, c->center);
        c->radius = number(window, "radius"); c->thickness = number(window, "thickness");
        c->index = number(window, "refractive_index");
        double previous = 0;
        for (int i = 1; i <= 4096; i++) {
            double radius = distorted(c, (PI/2-1e-7)*i/4096);
            if (!isfinite(radius) || radius <= previous) fail("non-monotonic radial spline");
            previous = radius;
        }
        lookup(c);
    }
    for (int i = 0; i < 4; i++) if (!cameras[i].present) fail("missing tracking camera");
    scan = profile;
    while (next(&scan, &f)) if (equal(f.name, "camera_extrinsics") && f.message) {
        Span id = find(f.value, "camera_id", 0, 1);
        for (int i = 0; i < 4; i++) if (equal(id, cameras[i].id)) {
            Camera *c = &cameras[i];
            if (c->extrinsics++) fail("duplicate camera extrinsics");
            if (!equal(find(f.value, "frame_id", 0, 1), "IMU_0")) fail("unsupported camera frame");
            Span transform = find(f.value, "frame_t_camera", 1, 1);
            vector(transform, "p", xyz, 3, c->position);
            vector(transform, "q", wxyz, 4, c->q);
            if (fabs(dot(c->q, c->q, 4)-1) > 1e-4 || dot(c->position,c->position,3) > .25)
                fail("invalid camera extrinsics");
        }
    }
    for (int i = 0; i < 4; i++) if (!cameras[i].extrinsics) fail("missing camera extrinsics");
}
static void rotation(const double *q, double r[3][3]) {
    double w=q[0], x=q[1], y=q[2], z=q[3];
    r[0][0]=1-2*(y*y+z*z); r[0][1]=2*(x*y-z*w); r[0][2]=2*(x*z+y*w);
    r[1][0]=2*(x*y+z*w); r[1][1]=1-2*(x*x+z*z); r[1][2]=2*(y*z-x*w);
    r[2][0]=2*(x*z-y*w); r[2][1]=2*(y*z+x*w); r[2][2]=1-2*(x*x+y*y);
}
static void geometry(Camera *c, const double *head) {
    double angle = sqrt(dot(head, head, 3));
    double scale = angle > 1e-15 ? sin(angle/2)/angle : .5;
    double q[4] = {cos(angle/2), head[0]*scale, head[1]*scale, head[2]*scale};
    double hr[3][3], cr[3][3]; rotation(q, hr); rotation(c->q, cr);
    /* inv(IMU_from_head) * IMU_from_camera; factory quaternion convention
       is transposed, exactly as in the validated host preparation. */
    for (int i = 0; i < 3; i++) {
        for (int j = 0; j < 3; j++) for (int k = 0; k < 3; k++)
            c->transform[4*i+j] += hr[k][i]*cr[j][k];
        for (int k = 0; k < 3; k++) c->transform[4*i+3] += hr[k][i]*(c->position[k]-head[k+3]);
        if (fabs(c->transform[4*i+3]) > .5) fail("head-to-camera translation out of range");
    }
    c->transform[15] = 1;
    for (int i = 0; i < 3; i++) for (int j = 0; j < 3; j++) {
        double product = dot(&c->transform[4*i], &c->transform[4*j], 3);
        if (!isfinite(product) || fabs(product-(i == j)) > 1e-4)
            fail("non-orthonormal camera rotation");
    }
}
static int map_pixel(const Camera *c, int x, int y, float *out) {
    double px=(x-c->principal[0])/c->focal[0], py=(y-c->principal[1])/c->focal[1];
    double radius=hypot(px,py), hi=PI/2-1e-7, lo=0;
    double limit=fmin(c->rd, distorted(c,atan(c->ru)));
    if (radius > limit || radius > distorted(c,hi)) return 0;
    for (int i=0;i<50;i++) {
        double mid=(lo+hi)/2;
        if (distorted(c,mid)<radius) lo=mid; else hi=mid;
    }
    double ur=tan((lo+hi)/2);
    if (ur>c->ru) return 0;
    double scale=radius>1e-12 ? ur/radius : 1;
    double ray[3]={px*scale+c->offset[0],py*scale+c->offset[1],1}; normalize(ray,3);
    double axis[3]={-c->center[0],-c->center[1],-c->center[2]}; normalize(axis,3);
    double position=fmax(0,fmin(999,(dot(ray,axis,3)+1)*999/2));
    int i=(int)position; if(i>998)i=998;
    double amount=c->correction[i]+(position-i)*(c->correction[i+1]-c->correction[i]);
    for(int j=0;j<3;j++)ray[j]-=amount*axis[j];
    normalize(ray,3);
    if(ray[2]<=0)return 0;
    double r=hypot(ray[0],ray[1]);
    scale=r>1e-12 ? 200*atan2(r,ray[2])/r : 200;
    double ox=ray[0]*scale+320, oy=ray[1]*scale+320;
    if(!(ox>=0 && ox<640 && oy>=0 && oy<640))return 0;
    out[0]=(float)ox;out[1]=(float)oy;return 1;
}
static FILE *output(const char *directory, const char *name) {
    char path[4096];
    if(snprintf(path,sizeof path,"%s/%s",directory,name)>=(int)sizeof path)fail("output path too long");
    FILE *f=fopen(path,"wb");if(!f)fail("cannot create calibration output");return f;
}
int main(int argc, char **argv) {
    if(argc!=4){fprintf(stderr,"Usage: gxr-prepare FACTORY_PROFILE HEAD_ORIGIN OUTPUT_DIRECTORY\n");return 2;}
    FILE *f=fopen(argv[1],"rb");if(!f)fail("factory profile unavailable");
    if(fseek(f,0,SEEK_END))fail("profile seek failed");
    long size=ftell(f);if(size<1 || size>16*1024*1024 || fseek(f,0,SEEK_SET))fail("profile size");
    char *data=malloc((size_t)size);if(!data)fail("out of memory");
    if(fread(data,1,(size_t)size,f)!=(size_t)size)fail("profile read failed");fclose(f);
    Camera cameras[4]={0};read_cameras((Span){data,data+size},cameras);free(data);
    double head[6];f=fopen(argv[2],"rb");if(!f)fail("runtime head origin unavailable");
    for(int i=0;i<6;i++)if(fscanf(f,"%lf",&head[i])!=1 || !isfinite(head[i]) || fabs(head[i])>(i<3?3.15:.5))fail("invalid runtime head origin");
    int extra;do{extra=fgetc(f);}while(extra!=EOF && isspace(extra));
    if(extra!=EOF)fail("unexpected head-origin data");fclose(f);
    for(int i=0;i<4;i++)geometry(&cameras[i],head);
    FILE *map=output(argv[3],"factory-map.bin");
    const uint32_t dimensions[3]={640,640,4};
    if(fwrite("GXRMAP1",1,8,map)!=8 || fwrite(dimensions,sizeof dimensions,1,map)!=1)fail("map write failed");
    for(int i=0;i<4;i++) {
        unsigned int count=0;
        for(int y=0;y<640;y++) {
            float row[640][2];
            for(int x=0;x<640;x++){row[x][0]=row[x][1]=-1;count+=map_pixel(&cameras[i],x,y,row[x]);}
            if(fwrite(row,sizeof row,1,map)!=1)fail("map write failed");
        }
        if(!count)fail("empty factory camera map");
        fprintf(stderr,"Factory camera %d: %u valid grid points\n",i,count);
    }
    if(fclose(map))fail("map close failed");
    FILE *cal=output(argv[3],"calibration.json");
    fputs("{\"kind\":\"galaxy_xr_sensor\",\"GxrCameraCalibration\":[",cal);
    for(int i=0;i<4;i++) {
        fprintf(cal,"%s{\"Id\":%d,\"ImageSize\":[640,640],\"SensorType\":\"s5k931\",\"Shutter\":{\"Type\":\"Global\"},\"Projection\":{\"Model\":\"PinholeXY\",\"Coefficients\":[200,200,320,320]},\"Distortion\":{\"Model\":\"Fisheye62\",\"Coefficients\":[0,0,0,0,0,0,0,0]},\"DeviceFromCamera\":[",i?",":"",i);
        for(int j=0;j<16;j++)fprintf(cal,"%s%.17g",j?",":"",cameras[i].transform[j]);
        fputs("]}",cal);
    }
    fputs("]}\n",cal);
    int bad=ferror(cal);if(fclose(cal)||bad)fail("calibration write failed");
    return 0;
}
