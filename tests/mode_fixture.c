/* Disposable UDP mode responder, not a game or a qualified artifact. */
#include <arpa/inet.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>
#ifndef FAIL_START
#define FAIL_START 0
#endif
int main(int argc,char **argv) {
 const char *game="mods/pml220",*home="/home/user/.callofduty4";
 for(int i=1;i+2<argc;i++) if(!strcmp(argv[i],"+set")) {
  if(!strcmp(argv[i+1],"fs_game"))game=argv[i+2];
  if(!strcmp(argv[i+1],"fs_homepath"))home=argv[i+2];
 }
 if(FAIL_START) {
  char path[512];snprintf(path,sizeof(path),"%s/private.cfg",home);
  FILE *file=fopen(path,"w");if(file){fputs("modified-by-failing-fixture",file);fclose(file);}
  for(;;)pause();
 }
 int fd=socket(AF_INET,SOCK_DGRAM,0);struct sockaddr_in address={.sin_family=AF_INET,.sin_port=htons(28960),.sin_addr.s_addr=INADDR_ANY};
 if(bind(fd,(struct sockaddr*)&address,sizeof(address)))return 2;
 char query[512],reply[1024];
 int size=snprintf(reply,sizeof(reply),"\xff\xff\xff\xffstatusResponse\n\\fs_game\\%s\\g_gametype\\%s\\sv_pure\\1\\mapname\\mp_crash\n",game,strstr(game,"btd")?"war":"sd");
 for(;;) {struct sockaddr_in peer;socklen_t length=sizeof(peer);int n=recvfrom(fd,query,sizeof(query),0,(struct sockaddr*)&peer,&length);if(n>0) {
  sendto(fd,reply,size,0,(struct sockaddr*)&peer,length);
  if(n==10 && !memcmp(query,"peer-probe",10)) {
   int ipc=socket(AF_UNIX,SOCK_SEQPACKET,0);struct sockaddr_un endpoint={.sun_family=AF_UNIX};
   strcpy(endpoint.sun_path,"/run/cod4-mode-bridge/control.sock");
   if(!connect(ipc,(struct sockaddr*)&endpoint,sizeof(endpoint)))send(ipc,"fixture-peer-proof",18,0);
   close(ipc);
  }
 }}
}
