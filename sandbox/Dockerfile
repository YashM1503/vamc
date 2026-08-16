# syntax=docker/dockerfile:1.7

# Supply a platform-appropriate, digest-pinned Python base image at build time.
# Example: --build-arg BASE_IMAGE=python:3.13-slim@sha256:<digest>
ARG BASE_IMAGE
FROM ${BASE_IMAGE}

ARG NUMPY_VERSION=2.4.6
ARG NUMBA_VERSION=0.66.0
ARG MESON_VERSION=1.8.3
ARG NINJA_VERSION=1.13.0

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install --yes --no-install-recommends \
        gfortran \
        gcc \
        g++ \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --no-cache-dir \
    "numpy==${NUMPY_VERSION}" \
    "numba==${NUMBA_VERSION}" \
    "meson==${MESON_VERSION}" \
    "ninja==${NINJA_VERSION}"

ENV HOME=/tmp \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONNOUSERSITE=1

WORKDIR /work
