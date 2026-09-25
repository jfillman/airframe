#!/usr/bin/env bash
# Compiles and packages the app inside the pipeline's Java build agent (eclipse-temurin:21-jdk),
# which runs natively on the build node. The Containerfile then only COPIES the jar in.
#
# Why not build inside the Containerfile (the scaffold's default)? The image is built for
# linux/arm64 and linux/amd64; the amd64 leg runs under QEMU emulation on the arm64 build node, and
# Maven on a JVM under emulation is very slow (~11 minutes for that leg, ~17 for the whole image,
# versus ~5 minutes for the native arm64 leg). Java bytecode is the same on both architectures, so compile once,
# natively, and let only the cheap packaging step run per architecture.
set -euo pipefail
cd "$(dirname "$0")"
./mvnw -B -ntp -DskipTests package
ls target/*.jar
