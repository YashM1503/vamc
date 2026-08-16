# ADR 0001: Evidence before optimization

- Status: Accepted
- Date: 2026-08-09

## Context

Modernized numerical code can be faster while silently changing mutation,
indexing, floating-point, or state semantics.

## Decision

VAMC separates candidate generation, verification, and benchmarking. A candidate
cannot enter benchmark ranking until it passes the configured verification
contract. Unknown loop dependencies fail closed. Generated optimization output
is treated only as a candidate proposal.

## Consequences

The system may modernize fewer routines or report smaller speedups than a
best-effort translator. Every accepted result can carry inspectable evidence,
and incorrect fast variants are discarded rather than promoted.
