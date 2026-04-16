# AGENTS.md

## Purpose

This file is an instruction template for agents working in the `franka_lerobot_teleop` repository.

Keep guidance practical, lightweight, and aligned with common ROS 2 development patterns. Prefer decisions that fit the existing workspace, package structure, and tooling unless the user explicitly asks for a different direction.

This is a prototyping repository. Do not prioritize backwards compatibility over the cleanest possible solution.

## Agent Priorities

Agents should:

- Follow ROS 2 style guidelines and established ecosystem conventions.
- Prioritize the simplest, most commonly used solution that satisfies the request.
- Stay consistent with the existing package layout, build tooling, launch structure, and container workflow.
- Avoid unnecessary abstractions, indirection, or novel patterns unless they clearly reduce maintenance burden.
- Clarify all non-trivial assumptions before relying on them in implementation or recommendations.

## ROS 2 Conventions

When making changes or proposing changes:

- Prefer standard ROS 2 package organization, naming, and file layout.
- Preserve common `colcon`/`ament` workflows and expectations.
- Follow existing conventions for launch files, configuration, parameters, and workspace structure.
- Use common ROS 2 ecosystem patterns before introducing custom alternatives.
- Keep container-related guidance compatible with normal ROS 2 development inside Docker or dev containers.

## Assumptions And Clarifications

Agents must make assumptions explicit in their responses whenever those assumptions affect implementation details, architecture, deployment, or user workflow.

Agents should:

- Treat missing non-obvious context as unresolved unless it can be inferred confidently from the repository.
- Pause and ask for clarification before making high-impact decisions.
- Call out tradeoffs when multiple reasonable approaches exist.
- Distinguish clearly between confirmed repository facts and inferred assumptions.

## Verification And User Next Steps

Agents should not create tests, run tests, launch files, simulations, hardware checks, runtime analysis, or other execution-heavy verification steps.

Instead, agents should:

- Leave builds, tests, and runtime verification to the user.
- Provide clear next-step commands the user can run manually.
- Recommend only the tests or checks that are necessary for the change.
- Briefly explain why each recommended verification step matters when the reason is not obvious.

## What Agents Should Avoid

Agents should not:

- Attempt to create,run, or build tests or runtime analysis.
- Run launch-based validation, simulation, or hardware-facing checks on the user's behalf.
- Introduce complex or uncommon solutions when a standard ROS 2 approach is sufficient.
- Hide important assumptions or proceed past unresolved high-impact ambiguity without surfacing it.
