# eggc from an egg checkout; egg-dev carries changes not yet merged.
EGG_DIR ?= $(HOME)/git/egg-dev
EGGC ?= ruby -I$(EGG_DIR)/lib $(EGG_DIR)/bin/eggc
CC ?= cc
# OpenSSL's libcrypto: Homebrew's on macOS, the system's elsewhere.
OPENSSL ?= $(shell test -d /usr/local/opt/openssl@3 && echo /usr/local/opt/openssl@3 || (test -d /opt/homebrew/opt/openssl@3 && echo /opt/homebrew/opt/openssl@3))
LIBDIRS = -L build $(if $(OPENSSL),-L $(OPENSSL)/lib)

build/campfire: build/libcfbcrypt.a $(wildcard src/*.egg src/*/*.egg)
	$(EGGC) build src/main.egg -o build/campfire $(LIBDIRS)

build/libcfbcrypt.a: vendor/crypt_blowfish/crypt_blowfish.c vendor/crypt_blowfish/bcrypt.c
	mkdir -p build
	$(CC) -O2 -c vendor/crypt_blowfish/crypt_blowfish.c -o build/crypt_blowfish.o
	$(CC) -O2 -c vendor/crypt_blowfish/bcrypt.c -o build/bcrypt.o
	ar rcs $@ build/crypt_blowfish.o build/bcrypt.o

check:
	$(EGGC) check src/main.egg

clean:
	rm -rf build

.PHONY: check clean
