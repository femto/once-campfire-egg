/* The one entry point once-campfire-egg calls: a name Egg can declare. */
#include "crypt_blowfish.h"

/* bcrypt of key under setting (a whole "$2a$12$..." digest works), into
   out; NULL if setting is not a bcrypt hash or out is too small. */
char *cf_bcrypt(const char *key, const char *setting, char *out, int size) {
    return _crypt_blowfish_rn(key, setting, out, size);
}

/* A "$2a$<cost>$" setting with a salt made from 16 random bytes, into out;
   NULL if out is too small. */
char *cf_bcrypt_gensalt(int cost, const char *random16, char *out, int size) {
    return _crypt_gensalt_blowfish_rn("$2a$", (unsigned long)cost, random16, 16, out, size);
}
