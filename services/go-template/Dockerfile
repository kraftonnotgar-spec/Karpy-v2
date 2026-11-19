# syntax=docker/dockerfile:1
# Build context: services/go-template
FROM golang:1.26-alpine AS build
WORKDIR /src
COPY go.mod ./
# go.sum appears once you add dependencies; uncomment then:
# COPY go.sum ./
RUN go mod download
COPY . .
ARG VERSION=dev
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w -X main.version=${VERSION}" -o /out/server ./cmd/server

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /out/server /server
USER nonroot:nonroot
ENV PORT=8080
EXPOSE 8080
# Distroless has no shell/curl; the binary probes itself.
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 CMD ["/server", "--healthcheck"]
ENTRYPOINT ["/server"]
