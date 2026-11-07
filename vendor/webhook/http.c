/* Bounded HTTP(S) transport for bot webhooks. No shell, redirects or proxies. */
#define _POSIX_C_SOURCE 200809L
#include <time.h>
#include <curl/curl.h>
#include <pthread.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#define MAX_REPLY (100 * 1024 * 1024)
struct reply { unsigned char *body; size_t len; char *type; long status; int error; int timed_out; double activity; double started; };
static pthread_once_t initialized = PTHREAD_ONCE_INIT;
static void initialize(void) { curl_global_init(CURL_GLOBAL_DEFAULT); }
static double now(void) {
    struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec + t.tv_nsec / 1000000000.0;
}
static int progress(void *context, curl_off_t total, curl_off_t downloaded, curl_off_t upload_total, curl_off_t uploaded) {
    (void)total; (void)downloaded; (void)upload_total; (void)uploaded;
    struct reply *r = context;
    if (now() - r->activity >= 7.0) { r->timed_out = 1; return 1; }
    return 0;
}
static size_t header(char *data, size_t size, size_t count, void *context) {
    (void)data; ((struct reply *)context)->activity = now();
    return size * count;
}
static size_t receive(char *data, size_t size, size_t count, void *context) {
    struct reply *r = context;
    r->activity = now();
    if (size && count > SIZE_MAX / size) return 0;
    size_t n = size * count;
    if (n > MAX_REPLY - r->len) return 0;
    void *p = realloc(r->body, r->len + n + 1);
    if (!p) return 0;
    r->body = p; memcpy(r->body + r->len, data, n); r->len += n;
    return n;
}
void *cf_webhook_post(const char *url, const unsigned char *payload, size_t length) {
    pthread_once(&initialized, initialize);
    struct reply *r = calloc(1, sizeof(*r));
    if (!r) return NULL;
    r->started = r->activity = now();
    CURL *c = curl_easy_init();
    if (!c) { r->error = CURLE_FAILED_INIT; return r; }
    struct curl_slist *headers = curl_slist_append(NULL, "Content-Type: application/json");
    headers = curl_slist_append(headers, "Expect:");
    curl_easy_setopt(c, CURLOPT_URL, url);
    curl_easy_setopt(c, CURLOPT_PROTOCOLS_STR, "http,https");
    curl_easy_setopt(c, CURLOPT_PROXY, "");
    curl_easy_setopt(c, CURLOPT_HTTPHEADER, headers);
    curl_easy_setopt(c, CURLOPT_POSTFIELDS, payload);
    curl_easy_setopt(c, CURLOPT_POSTFIELDSIZE_LARGE, (curl_off_t)length);
    curl_easy_setopt(c, CURLOPT_CONNECTTIMEOUT, 7L);
    curl_easy_setopt(c, CURLOPT_NOPROGRESS, 0L);
    curl_easy_setopt(c, CURLOPT_XFERINFOFUNCTION, progress);
    curl_easy_setopt(c, CURLOPT_XFERINFODATA, r);
    curl_easy_setopt(c, CURLOPT_HEADERFUNCTION, header);
    curl_easy_setopt(c, CURLOPT_HEADERDATA, r);
    curl_easy_setopt(c, CURLOPT_TIMEOUT, 60L);
    curl_easy_setopt(c, CURLOPT_NOSIGNAL, 1L);
    curl_easy_setopt(c, CURLOPT_ACCEPT_ENCODING, "");
    curl_easy_setopt(c, CURLOPT_WRITEFUNCTION, receive);
    curl_easy_setopt(c, CURLOPT_WRITEDATA, r);
    r->error = curl_easy_perform(c);
    if (r->timed_out) r->error = CURLE_OPERATION_TIMEDOUT;
    curl_easy_getinfo(c, CURLINFO_RESPONSE_CODE, &r->status);
    char *type = NULL;
    curl_easy_getinfo(c, CURLINFO_CONTENT_TYPE, &type);
    if (type) { r->type = malloc(strlen(type) + 1); if (r->type) strcpy(r->type, type); }
    curl_slist_free_all(headers); curl_easy_cleanup(c);
    return r;
}
const unsigned char *cf_webhook_body(struct reply *r) { return r->body; }
size_t cf_webhook_length(struct reply *r) { return r->len; }
const char *cf_webhook_type(struct reply *r) { return r->type ? r->type : ""; }
size_t cf_webhook_type_length(struct reply *r) { return r->type ? strlen(r->type) : 0; }
long cf_webhook_status(struct reply *r) { return r->status; }
int cf_webhook_error(struct reply *r) { return r->error; }
void cf_webhook_free(struct reply *r) { if (r) { free(r->body); free(r->type); free(r); } }

long cf_webhook_timeout(struct reply *r) { return r->timed_out || now() - r->started < 59.0 ? 7 : 60; }

#include <openssl/evp.h>
int cf_flash_seal(const unsigned char *key, const unsigned char *nonce, const unsigned char *data, int length, unsigned char *out) {
    EVP_CIPHER_CTX *c=EVP_CIPHER_CTX_new();int n=0, tail=0, ok=0;
    if (!c) return -1;
    if (EVP_EncryptInit_ex(c,EVP_aes_256_gcm(),NULL,key,nonce)==1 && EVP_EncryptUpdate(c,out,&n,data,length)==1 && EVP_EncryptFinal_ex(c,out+n,&tail)==1 && EVP_CIPHER_CTX_ctrl(c,EVP_CTRL_GCM_GET_TAG,16,out+n+tail)==1) ok=n+tail+16;
    EVP_CIPHER_CTX_free(c);return ok?ok:-1;
}
int cf_flash_open(const unsigned char *key, const unsigned char *nonce, const unsigned char *data, int length, unsigned char *out) {
    EVP_CIPHER_CTX *c=EVP_CIPHER_CTX_new();int n=0,tail=0,ok=-1;
    if (!c || length<16) { EVP_CIPHER_CTX_free(c);return -1; }
    if (EVP_DecryptInit_ex(c,EVP_aes_256_gcm(),NULL,key,nonce)==1 && EVP_DecryptUpdate(c,out,&n,data,length-16)==1 && EVP_CIPHER_CTX_ctrl(c,EVP_CTRL_GCM_SET_TAG,16,(void *)(data+length-16))==1 && EVP_DecryptFinal_ex(c,out+n,&tail)==1) ok=n+tail;
    EVP_CIPHER_CTX_free(c);return ok;
}

#include <arpa/inet.h>
#include <netdb.h>
#include <fcntl.h>
static int public_address(const struct sockaddr *address) {
    if (address->sa_family==AF_INET) {
        unsigned long ip=ntohl(((const struct sockaddr_in *)address)->sin_addr.s_addr);
        return !(ip>>24==0||ip>>24==10||ip>>24==127||ip>>24>=224||ip>>20==0xAC1||ip>>16==0xC0A8||ip>>16==0xA9FE||ip>>22==0x191||ip>>17==0x6309||(ip>>24==192&&((ip>>16)&255)==0));
    }
    if (address->sa_family==AF_INET6) {
        const unsigned char *ip=((const struct sockaddr_in6 *)address)->sin6_addr.s6_addr;
        return (ip[0]&0xE0)==0x20; /* global unicast only */
    }
    return 0;
}
static curl_socket_t public_socket(void *context,curlsocktype purpose,struct curl_sockaddr *address) {
    (void)context;(void)purpose;
    if (!public_address(&address->addr)) return CURL_SOCKET_BAD;
    int fd=socket(address->family,address->socktype,address->protocol);
    if(fd>=0)fcntl(fd,F_SETFD,FD_CLOEXEC);
    return fd;
}
int cf_push_url_valid(const char *url,int allow_local) {
    pthread_once(&initialized,initialize);
    CURLU *u=curl_url();char *scheme=NULL,*host=NULL,*user=NULL;int ok=0;
    if (!u||curl_url_set(u,CURLUPART_URL,url,0)||curl_url_get(u,CURLUPART_SCHEME,&scheme,0)||curl_url_get(u,CURLUPART_HOST,&host,0)) goto done;
    if (strcmp(scheme,"https") && !(allow_local&&!strcmp(scheme,"http"))) goto done;
    if (curl_url_get(u,CURLUPART_USER,&user,0)==CURLUE_OK) goto done;
    if (allow_local) { ok=1;goto done; }
    struct addrinfo hints={0},*addresses=NULL;hints.ai_socktype=SOCK_STREAM;
    if (!getaddrinfo(host,NULL,&hints,&addresses)) {
        ok=1;for(struct addrinfo *a=addresses;a;a=a->ai_next) if(!public_address(a->ai_addr)) ok=0;
        freeaddrinfo(addresses);
    }
 done: curl_free(scheme);curl_free(host);curl_free(user);curl_url_cleanup(u);return ok;
}
int cf_push_post(const char *url,const unsigned char *body,int length,const char *authorization,int allow_local) {
    pthread_once(&initialized,initialize);CURL *c=curl_easy_init();if(!c)return -1;
    struct curl_slist *headers=NULL;
    headers=curl_slist_append(headers,"Content-Encoding: aes128gcm");headers=curl_slist_append(headers,"Content-Type: application/octet-stream");headers=curl_slist_append(headers,"TTL: 2419200");headers=curl_slist_append(headers,"Urgency: normal");headers=curl_slist_append(headers,authorization);headers=curl_slist_append(headers,"Expect:");
    struct reply r={0};r.started=r.activity=now();
    curl_easy_setopt(c,CURLOPT_URL,url);curl_easy_setopt(c,CURLOPT_PROTOCOLS_STR,allow_local?"http,https":"https");curl_easy_setopt(c,CURLOPT_PROXY,"");curl_easy_setopt(c,CURLOPT_HTTPHEADER,headers);curl_easy_setopt(c,CURLOPT_POSTFIELDS,body);curl_easy_setopt(c,CURLOPT_POSTFIELDSIZE,(long)length);curl_easy_setopt(c,CURLOPT_CONNECTTIMEOUT,7L);curl_easy_setopt(c,CURLOPT_TIMEOUT,10L);curl_easy_setopt(c,CURLOPT_NOSIGNAL,1L);curl_easy_setopt(c,CURLOPT_WRITEFUNCTION,receive);curl_easy_setopt(c,CURLOPT_WRITEDATA,&r);
    if (!allow_local) curl_easy_setopt(c,CURLOPT_OPENSOCKETFUNCTION,public_socket);
    CURLcode error=curl_easy_perform(c);long status=0;curl_easy_getinfo(c,CURLINFO_RESPONSE_CODE,&status);
    free(r.body);curl_slist_free_all(headers);curl_easy_cleanup(c);return error==CURLE_OK?(int)status:-1;
}
static size_t receive_metadata(char *data,size_t size,size_t count,void *context) {
    struct reply *r=context;
    if(size&&count>SIZE_MAX/size)return 0;
    if(size*count>1048576-r->len)return 0;
    return receive(data,size,count,context);
}
void *cf_unfurl_get(const char *url) {
    pthread_once(&initialized,initialize);
    struct reply *r=calloc(1,sizeof(*r));if(!r)return NULL;
    CURL *c=curl_easy_init();if(!c){r->error=CURLE_FAILED_INIT;return r;}
    r->activity=r->started=now();
    curl_easy_setopt(c,CURLOPT_URL,url);curl_easy_setopt(c,CURLOPT_PROTOCOLS_STR,"http,https");curl_easy_setopt(c,CURLOPT_PROXY,"");curl_easy_setopt(c,CURLOPT_OPENSOCKETFUNCTION,public_socket);curl_easy_setopt(c,CURLOPT_CONNECTTIMEOUT,3L);curl_easy_setopt(c,CURLOPT_TIMEOUT,5L);curl_easy_setopt(c,CURLOPT_NOSIGNAL,1L);curl_easy_setopt(c,CURLOPT_ACCEPT_ENCODING,"");curl_easy_setopt(c,CURLOPT_WRITEFUNCTION,receive_metadata);curl_easy_setopt(c,CURLOPT_WRITEDATA,r);
    r->error=curl_easy_perform(c);curl_easy_getinfo(c,CURLINFO_RESPONSE_CODE,&r->status);
    char *type=NULL;curl_easy_getinfo(c,CURLINFO_CONTENT_TYPE,&type);if(type){r->type=malloc(strlen(type)+1);if(r->type)strcpy(r->type,type);}
    curl_easy_cleanup(c);return r;
}
