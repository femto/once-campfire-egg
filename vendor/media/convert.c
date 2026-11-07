#define _POSIX_C_SOURCE 200809L
#include <spawn.h>
#include <sys/wait.h>
#include <signal.h>
#include <time.h>
#include <unistd.h>
#include <stdio.h>
extern char **environ;
/* Decode only a caller-selected raster format. Arguments never enter a shell. */
int cf_image_convert(const char *input, const char *output) {
    char *argv[] = {"convert", "-limit", "memory", "64MiB", "-limit", "map", "128MiB", "-limit", "disk", "0", (char *)input, "-auto-orient", "-strip", "-thumbnail", "512x512>", (char *)output, NULL};
    pid_t pid;
    if (posix_spawnp(&pid, "convert", NULL, NULL, argv, environ)) return -1;
    struct timespec pause = {0, 100000000};
    for (int i=0; i<150; i++) {
        int status;
        if (waitpid(pid,&status,WNOHANG)==pid) return WIFEXITED(status) && WEXITSTATUS(status)==0 ? 0 : -1;
        nanosleep(&pause,NULL);
    }
    kill(pid,SIGKILL); waitpid(pid,NULL,0); return -1;
}
int cf_video_preview(const char *input, const char *output, const char *format) {
    char *argv[] = {"ffmpeg", "-nostdin", "-v", "error", "-max_alloc", "67108864", "-protocol_whitelist", "file,pipe", "-f", (char *)format, "-i", (char *)input, "-frames:v", "1", "-vf", "scale=512:-2", "-c:v", "png", "-y", (char *)output, NULL};
    pid_t pid;
    if (posix_spawnp(&pid, "ffmpeg", NULL, NULL, argv, environ)) return -1;
    struct timespec pause={0,100000000};
    for (int i=0;i<150;i++) { int status; if (waitpid(pid,&status,WNOHANG)==pid) return WIFEXITED(status)&&WEXITSTATUS(status)==0?0:-1; nanosleep(&pause,NULL); }
    kill(pid,SIGKILL);waitpid(pid,NULL,0);return -1;
}
int cf_image_icon(const char *input,const char *output,int size) {
    if(size!=192&&size!=512)return -1;
    char geometry[32];snprintf(geometry,sizeof(geometry),"%dx%d",size,size);
    char *argv[]={"convert","-limit","memory","64MiB","-limit","map","128MiB","-limit","disk","0",(char *)input,"-resize",geometry,"-background","none","-gravity","center","-extent",geometry,(char *)output,NULL};
    pid_t pid;if(posix_spawnp(&pid,"convert",NULL,NULL,argv,environ))return -1;
    struct timespec pause={0,100000000};
    for(int i=0;i<150;i++){int status;if(waitpid(pid,&status,WNOHANG)==pid)return WIFEXITED(status)&&WEXITSTATUS(status)==0?0:-1;nanosleep(&pause,NULL);}
    kill(pid,SIGKILL);waitpid(pid,NULL,0);return -1;
}
