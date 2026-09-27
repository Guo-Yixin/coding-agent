FROM alpine:3.20

# SandboxEvalRunner builds a git baseline and diff inside the sandbox. Keep this
# small image for the OpenSandbox transport/isolation smoke case only.
RUN apk add --no-cache git
