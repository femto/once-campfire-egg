#define _POSIX_C_SOURCE 200809L
#define OPENSSL_SUPPRESS_DEPRECATED
#include <openssl/ec.h>
#include <openssl/ecdsa.h>
#include <openssl/obj_mac.h>
#include <openssl/hmac.h>
#include <openssl/evp.h>
#include <openssl/rand.h>
#include <string.h>
#include <stdlib.h>

static EC_KEY *private_key(const unsigned char *data) {
    EC_KEY *key=EC_KEY_new_by_curve_name(NID_X9_62_prime256v1);
    BIGNUM *n=BN_bin2bn(data,32,NULL), *order=BN_new();
    EC_POINT *point=key?EC_POINT_new(EC_KEY_get0_group(key)):NULL;
    if (!key||!n||!order||!point||!EC_GROUP_get_order(EC_KEY_get0_group(key),order,NULL)||BN_is_zero(n)||BN_cmp(n,order)>=0||!EC_KEY_set_private_key(key,n)||!EC_POINT_mul(EC_KEY_get0_group(key),point,n,NULL,NULL,NULL)||!EC_KEY_set_public_key(key,point)) { EC_KEY_free(key);key=NULL; }
    BN_clear_free(n);BN_free(order);EC_POINT_free(point);return key;
}
int cf_push_public(const unsigned char *private_bytes, unsigned char *out) {
    EC_KEY *key=private_key(private_bytes);if (!key) return 0;
    int n=EC_POINT_point2oct(EC_KEY_get0_group(key),EC_KEY_get0_public_key(key),POINT_CONVERSION_UNCOMPRESSED,out,65,NULL);
    EC_KEY_free(key);return n==65;
}
int cf_push_sign(const unsigned char *private_bytes, const unsigned char *data, int len, unsigned char *out) {
    EC_KEY *key=private_key(private_bytes);if (!key) return 0;
    unsigned char digest[32];EVP_Digest(data,len,digest,NULL,EVP_sha256(),NULL);
    ECDSA_SIG *sig=ECDSA_do_sign(digest,32,key);int ok=0;
    if (sig) { const BIGNUM *r,*s;ECDSA_SIG_get0(sig,&r,&s);ok=BN_bn2binpad(r,out,32)==32 && BN_bn2binpad(s,out+32,32)==32; }
    ECDSA_SIG_free(sig);EC_KEY_free(key);return ok;
}
int cf_push_valid(const unsigned char *public_bytes,int n) {
    if (n!=65||public_bytes[0]!=4) return 0;
    EC_GROUP *g=EC_GROUP_new_by_curve_name(NID_X9_62_prime256v1);EC_POINT *p=g?EC_POINT_new(g):NULL;
    int ok=g&&p&&EC_POINT_oct2point(g,p,public_bytes,n,NULL)&&EC_POINT_is_on_curve(g,p,NULL)&&!EC_POINT_is_at_infinity(g,p);
    EC_POINT_free(p);EC_GROUP_free(g);return ok;
}
static int hkdf(const unsigned char *salt,int salt_len,const unsigned char *input,int input_len,const unsigned char *info,int info_len,unsigned char *out,int n) {
    unsigned char key[32],block[32],buffer[256];unsigned int size;
    if (info_len>=255||n>32) return 0;
    if (!HMAC(EVP_sha256(),salt,salt_len,input,input_len,key,&size)) return 0;
    memcpy(buffer,info,info_len);buffer[info_len]=1;
    if (!HMAC(EVP_sha256(),key,32,buffer,info_len+1,block,&size)) return 0;
    memcpy(out,block,n);return 1;
}
/* RFC 8291, one aes128gcm record. Caller provides payload+104 output bytes. */
int cf_push_encrypt(const unsigned char *client_public,const unsigned char *auth,const unsigned char *payload,int len,unsigned char *out) {
    if (len<1||len>3992||!cf_push_valid(client_public,65)) return -1;
    EC_KEY *server=EC_KEY_new_by_curve_name(NID_X9_62_prime256v1);EC_POINT *client=NULL;EVP_CIPHER_CTX *cipher=NULL;
    unsigned char shared[32],info[144],ikm[32],cek[16],nonce[12],plain[3994],tag[16];int result=-1,n=0,tail=0;
    if (!server||!EC_KEY_generate_key(server)) goto done;
    client=EC_POINT_new(EC_KEY_get0_group(server));
    if (!client||!EC_POINT_oct2point(EC_KEY_get0_group(server),client,client_public,65,NULL)||ECDH_compute_key(shared,32,client,server,NULL)!=32||RAND_bytes(out,16)!=1) goto done;
    out[20]=65;
    if (EC_POINT_point2oct(EC_KEY_get0_group(server),EC_KEY_get0_public_key(server),POINT_CONVERSION_UNCOMPRESSED,out+21,65,NULL)!=65) goto done;
    memcpy(info,"WebPush: info",13);info[13]=0;memcpy(info+14,client_public,65);memcpy(info+79,out+21,65);
    if (!hkdf(auth,16,shared,32,info,144,ikm,32)||!hkdf(out,16,ikm,32,(const unsigned char *)"Content-Encoding: aes128gcm\0",28,cek,16)||!hkdf(out,16,ikm,32,(const unsigned char *)"Content-Encoding: nonce\0",24,nonce,12)) goto done;
    memcpy(plain,payload,len);plain[len]=2;plain[len+1]=0;
    cipher=EVP_CIPHER_CTX_new();
    if (!cipher||!EVP_EncryptInit_ex(cipher,EVP_aes_128_gcm(),NULL,cek,nonce)||!EVP_EncryptUpdate(cipher,out+86,&n,plain,len+2)||!EVP_EncryptFinal_ex(cipher,out+86+n,&tail)||!EVP_CIPHER_CTX_ctrl(cipher,EVP_CTRL_GCM_GET_TAG,16,tag)) goto done;
    memcpy(out+86+n+tail,tag,16);int size=n+tail+16;
    out[16]=(size>>24)&255;out[17]=(size>>16)&255;out[18]=(size>>8)&255;out[19]=size&255;result=86+size;
 done:
    EVP_CIPHER_CTX_free(cipher);EC_POINT_free(client);EC_KEY_free(server);return result;
}
