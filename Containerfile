# Container image for Freezy Arena.
#
# Build:  podman build -t localhost/freezy-arena:latest .
# Run:    see deploy/freezy-arena.container (rootless Quadlet unit).
#
# The server reads templates/, static/, schedules/ and font/ from its working directory and writes its
# state next to them. Everything it writes is redirected into /data by the symlinks below, so one
# volume mounted at /data holds the event database, backups, match logs and team avatars.

FROM docker.io/library/golang:1.26 AS builder
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
# Static binary with embedded timezone data, so the runtime image needs neither glibc parity nor tzdata.
RUN CGO_ENABLED=0 go build -tags timetzdata -o /out/cheesy-arena .

FROM registry.access.redhat.com/ubi9/ubi-minimal:latest
WORKDIR /app
COPY --from=builder /out/cheesy-arena ./
COPY templates ./templates
COPY static ./static
COPY schedules ./schedules
COPY font ./font
RUN mkdir -p /data/db /data/logs \
 && mv static/img/avatars /data/avatars \
 && ln -s /data/avatars static/img/avatars \
 && ln -s /data/logs static/logs \
 && ln -s /data/db db \
 && ln -s /data/event.db event.db
VOLUME /data
EXPOSE 8080
ENTRYPOINT ["/app/cheesy-arena"]
