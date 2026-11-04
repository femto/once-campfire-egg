# ONCE Campfire in Egg, laid out as once-campfire-rust's image is for
# once-campfire-verification: /rails as the working directory, the seed
# mounted at /rails/storage/db and /rails/storage/files, port HTTP_PORT.
# The assets come from the build context: run script/assets.sh build/assets
# first.
ARG DEBIAN_RELEASE=trixie
# egg main with #74-#77 (FFI bytes, args.env, constants, time and rand).
ARG EGG_REF=f5fba8f
# gzip through zlib-ng's zlib-compatible build, linked statically: the Rust
# app deflates with zlib-rs, of the same speed, and stock zlib is slower.
ARG ZLIB_NG_VERSION=2.2.4
ARG ZLIB_NG_SHA256=a73343c3093e5cdc50d9377997c3815b878fd110bf6511c2c7759f2afb90f5a3

FROM docker.io/library/debian:${DEBIAN_RELEASE} AS build
ARG EGG_REF
ARG ZLIB_NG_VERSION
ARG ZLIB_NG_SHA256
RUN apt-get update -qq && \
    apt-get install --no-install-recommends -y \
      ca-certificates curl cmake git ruby gcc libc6-dev make libsqlite3-dev libssl-dev
RUN curl -sfL -o /tmp/zlib-ng.tar.gz https://github.com/zlib-ng/zlib-ng/archive/refs/tags/${ZLIB_NG_VERSION}.tar.gz && \
    echo "${ZLIB_NG_SHA256}  /tmp/zlib-ng.tar.gz" | sha256sum -c - && \
    tar -xzf /tmp/zlib-ng.tar.gz -C /tmp && \
    cmake -S /tmp/zlib-ng-${ZLIB_NG_VERSION} -B /tmp/zlib-ng-build -DZLIB_COMPAT=ON -DBUILD_SHARED_LIBS=OFF \
      -DZLIB_ENABLE_TESTS=OFF -DZLIBNG_ENABLE_TESTS=OFF -DWITH_GTEST=OFF -DCMAKE_BUILD_TYPE=Release \
      -DCMAKE_POSITION_INDEPENDENT_CODE=ON -DCMAKE_INSTALL_PREFIX=/opt/zlib-ng && \
    cmake --build /tmp/zlib-ng-build -j"$(nproc)" && cmake --install /tmp/zlib-ng-build
RUN git clone https://github.com/femto/egg.git /egg && git -C /egg checkout ${EGG_REF}
WORKDIR /src
COPY Makefile ./
COPY script script
COPY src src
COPY templates templates
COPY vendor vendor
RUN make EGG_DIR=/egg OPENSSL= EXTRA_LIBDIRS="-L /opt/zlib-ng/lib" && install -D -m 755 build/campfire /out/campfire

FROM docker.io/library/debian:${DEBIAN_RELEASE}-slim
RUN apt-get update -qq && \
    apt-get install --no-install-recommends -y libsqlite3-0 libssl3t64 && \
    rm -rf /var/lib/apt/lists /var/cache/apt/archives
RUN groupadd --system --gid 1000 rails && \
    useradd rails --uid 1000 --gid 1000 --create-home --shell /bin/bash
WORKDIR /rails
COPY --from=build /out/campfire /usr/local/bin/campfire
COPY build/assets /rails/assets
RUN mkdir -p /rails/storage/db /rails/storage/files && chown -R 1000:1000 /rails
USER 1000:1000
ENV CAMPFIRE_STORAGE_PATH=/rails/storage CAMPFIRE_ASSETS_PATH=/rails/assets HTTP_PORT=80
EXPOSE 80
CMD ["/usr/local/bin/campfire"]
