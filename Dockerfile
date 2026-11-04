# ONCE Campfire in Egg, laid out as once-campfire-rust's image is for
# once-campfire-verification: /rails as the working directory, the seed
# mounted at /rails/storage/db and /rails/storage/files, port HTTP_PORT.
# The assets come from the build context: run script/assets.sh build/assets
# RUST_URL first.
ARG DEBIAN_RELEASE=trixie
# egg main with #74-#77 (FFI bytes, args.env, constants, time and rand).
ARG EGG_REF=f5fba8f

FROM docker.io/library/debian:${DEBIAN_RELEASE} AS build
ARG EGG_REF
RUN apt-get update -qq && \
    apt-get install --no-install-recommends -y \
      ca-certificates git ruby gcc libc6-dev make libsqlite3-dev zlib1g-dev libssl-dev
RUN git clone https://github.com/femto/egg.git /egg && git -C /egg checkout ${EGG_REF}
WORKDIR /src
COPY Makefile ./
COPY script script
COPY src src
COPY templates templates
COPY vendor vendor
RUN make EGG_DIR=/egg OPENSSL= && install -D -m 755 build/campfire /out/campfire

FROM docker.io/library/debian:${DEBIAN_RELEASE}-slim
RUN apt-get update -qq && \
    apt-get install --no-install-recommends -y libsqlite3-0 zlib1g libssl3t64 && \
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
