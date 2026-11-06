# eggc from an egg checkout at main.
EGG_DIR ?= $(HOME)/crystal-project/egg
EGGC ?= ruby -I$(EGG_DIR)/lib $(EGG_DIR)/bin/eggc
CC ?= cc
# OpenSSL's libcrypto: Homebrew's on macOS, the system's elsewhere.
OPENSSL ?= $(shell test -d /usr/local/opt/openssl@3 && echo /usr/local/opt/openssl@3 || (test -d /opt/homebrew/opt/openssl@3 && echo /opt/homebrew/opt/openssl@3))
# EXTRA_LIBDIRS: another zlib, say (the Docker image links zlib-ng).
LIBDIRS = -L build $(EXTRA_LIBDIRS) $(if $(OPENSSL),-L $(OPENSSL)/lib)

build/campfire: build/libcfbcrypt.a build/libcfsys.a src/views.egg $(wildcard src/*.egg src/*/*.egg)
	$(EGGC) build src/main.egg -o build/campfire $(LIBDIRS)

src/views.egg: script/templates.rb $(wildcard templates/*)
	ruby script/templates.rb > $@

build/libcfbcrypt.a: vendor/crypt_blowfish/crypt_blowfish.c vendor/crypt_blowfish/bcrypt.c
	mkdir -p build
	$(CC) -O2 -c vendor/crypt_blowfish/crypt_blowfish.c -o build/crypt_blowfish.o
	$(CC) -O2 -c vendor/crypt_blowfish/bcrypt.c -o build/bcrypt.o
	ar rcs $@ build/crypt_blowfish.o build/bcrypt.o

build/libcfsys.a: vendor/sys/nofile.c
	mkdir -p build
	$(CC) -O2 -c vendor/sys/nofile.c -o build/nofile.o
	ar rcs $@ build/nofile.o

check: src/views.egg
	$(EGGC) check src/main.egg

clean:
	rm -rf build

.PHONY: check clean
