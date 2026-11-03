# eggc from an egg checkout; egg-dev carries changes not yet merged.
EGG_DIR ?= $(HOME)/git/egg-dev
EGGC ?= ruby -I$(EGG_DIR)/lib $(EGG_DIR)/bin/eggc

build/campfire: $(wildcard src/*.egg src/*/*.egg)
	mkdir -p build
	$(EGGC) build src/main.egg -o build/campfire

check:
	$(EGGC) check src/main.egg

clean:
	rm -rf build

.PHONY: check clean
