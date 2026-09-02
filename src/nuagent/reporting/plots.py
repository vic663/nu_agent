"""Matplotlib figures for the report (Agg backend, no display needed)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402


def plot_residuals(history: dict[str, list[float]], path: Path) -> Path | None:
    if not history:
        return None
    fig, ax = plt.subplots(figsize=(6, 3.6))
    for field, hist in history.items():
        if field == "Uz" or not hist:
            continue
        ax.semilogy(np.linspace(0, 1, len(hist)), hist, label=field, lw=1.2)
    ax.set_xlabel("normalised iteration")
    ax.set_ylabel("initial residual")
    ax.set_title("Residual history")
    ax.grid(True, which="both", alpha=0.3)
    ax.legend(fontsize=8, ncol=3)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)
    return path


def plot_profiles(
    spec: dict[str, Any], profiles: dict[str, Any], validation: dict[str, Any], path: Path
) -> Path | None:
    kind = spec["case"]["kind"]
    if kind == "ribbed_tube" and "module_Nu" in profiles:
        return _plot_ribbed(spec, profiles, validation, path)
    if kind == "heated_pipe" and "x" in profiles and "Nu_local" in profiles:
        D = spec["case"]["diameter"]
        x = np.array(profiles["x"]) / D
        fig, axes = plt.subplots(1, 2, figsize=(9, 3.6))
        axes[0].plot(x, profiles["Nu_local"], lw=1.5, label="CFD (local)")
        ref = validation.get("results", {}).get("Nu", {})
        if "reference" in ref:
            band = ref.get("reference_uncertainty", 0.0)
            axes[0].axhline(ref["reference"], color="k", ls="--", lw=1, label=f"{ref['source']}")
            if band:
                axes[0].axhspan(
                    ref["reference"] * (1 - band),
                    ref["reference"] * (1 + band),
                    color="k",
                    alpha=0.08,
                )
        finite = np.isfinite(profiles["Nu_local"])
        if finite.any():
            ymax = np.percentile(np.array(profiles["Nu_local"])[finite], 90) * 1.8
            axes[0].set_ylim(0, ymax)
        axes[0].set_xlabel("x / D")
        axes[0].set_ylabel("Nu")
        axes[0].set_title("Local Nusselt number")
        axes[0].grid(alpha=0.3)
        axes[0].legend(fontsize=8)
        axes[1].plot(x, profiles["T_wall"], label="T_wall (CFD)")
        axes[1].plot(x, profiles["T_bulk"], label="T_bulk (energy balance)")
        axes[1].set_xlabel("x / D")
        axes[1].set_ylabel("T [K]")
        axes[1].set_title("Wall and bulk temperature")
        axes[1].grid(alpha=0.3)
        axes[1].legend(fontsize=8)
        fig.tight_layout()
        fig.savefig(path, dpi=130)
        plt.close(fig)
        return path
    if kind == "permeation" and "t" in profiles:
        fig, ax = plt.subplots(figsize=(6, 3.6))
        ax.plot(profiles["t"], profiles["flux_downstream"], label="FESTIM")
        ax.set_xlabel("t [s]")
        ax.set_ylabel("downstream flux [1/m²/s]")
        ax.set_title("Permeation transient")
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8)
        fig.tight_layout()
        fig.savefig(path, dpi=130)
        plt.close(fig)
        return path
    if kind == "tds" and "temperature" in profiles:
        fig, ax = plt.subplots(figsize=(6, 3.6))
        ax.plot(profiles["temperature"], profiles["desorption_flux"])
        ax.set_xlabel("T [K]")
        ax.set_ylabel("desorption flux [1/m²/s]")
        ax.set_title("Thermal desorption spectrum")
        ax.grid(alpha=0.3)
        fig.tight_layout()
        fig.savefig(path, dpi=130)
        plt.close(fig)
        return path
    return None


def plot_gci(verification: dict[str, Any], path: Path) -> Path | None:
    levels = verification.get("levels", [])
    gci = verification.get("gci", {})
    if len(levels) < 2 or not gci:
        return None
    fig, axes = plt.subplots(1, len(gci), figsize=(4.2 * len(gci), 3.4), squeeze=False)
    for ax, (q, g) in zip(axes[0], gci.items(), strict=False):
        h = np.array(g["h"])
        f = np.array(g["f"])
        ax.plot(h, f, "o-", label="computed")
        if g.get("extrapolated") is not None:
            ax.axhline(
                g["extrapolated"],
                color="C1",
                ls="--",
                label=f"Richardson (p={g['observed_order']:.2f})",
            )
        ex = verification.get("exact_error", {}).get(q, {}).get("exact")
        if ex is not None:
            ax.axhline(ex, color="k", ls=":", label="exact")
        ax.set_xscale("log")
        ax.set_xlabel("representative cell size h [m]")
        ax.set_ylabel(q)
        ax.set_title(f"Grid convergence: {q}")
        ax.grid(alpha=0.3)
        ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)
    return path


def plot_posterior(
    samples: np.ndarray, names: list[str], truths: dict[str, float] | None, path: Path
) -> Path:
    n = samples.shape[1]
    fig, axes = plt.subplots(1, n, figsize=(3.4 * n, 3.2), squeeze=False)
    for i, (ax, name) in enumerate(zip(axes[0], names, strict=True)):
        ax.hist(samples[:, i], bins=40, color="C0", alpha=0.8, density=True)
        if truths and name in truths:
            ax.axvline(truths[name], color="k", ls="--", label="truth")
            ax.legend(fontsize=7)
        ax.set_xlabel(name)
        ax.set_yticks([])
    fig.suptitle("Marginal posteriors")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)
    return path


def plot_sobol(
    first: dict[str, float], total: dict[str, float], path: Path, title: str = "Sobol indices"
) -> Path:
    names = list(first)
    x = np.arange(len(names))
    fig, ax = plt.subplots(figsize=(5.5, 3.4))
    ax.bar(x - 0.18, [first[n] for n in names], 0.36, label="S1 (first order)")
    ax.bar(x + 0.18, [total[n] for n in names], 0.36, label="ST (total)")
    ax.set_xticks(x)
    ax.set_xticklabels(names, rotation=20)
    ax.set_ylabel("index")
    ax.set_title(title)
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)
    return path


def _plot_ribbed(
    spec: dict[str, Any], profiles: dict[str, Any], validation: dict[str, Any], path: Path
) -> Path:
    D = spec["case"]["diameter"]
    x = np.array(profiles["x"]) / D
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.6))
    n_mod = len(profiles["module_Nu"])
    axes[0].bar(range(1, n_mod + 1), profiles["module_Nu"], color="C0", label="CFD, per pitch")
    ref = validation.get("results", {}).get("Nu", {})
    if "reference" in ref:
        band = ref.get("reference_uncertainty", 0.0)
        axes[0].axhline(ref["reference"], color="k", ls="--", lw=1, label=ref["source"])
        if band:
            axes[0].axhspan(
                ref["reference"] * (1 - band), ref["reference"] * (1 + band), color="k", alpha=0.08
            )
    axes[0].set_xlabel("developed module")
    axes[0].set_ylabel("Nu (nominal area)")
    axes[0].set_title("Module-averaged Nusselt number")
    axes[0].grid(alpha=0.3, axis="y")
    axes[0].legend(fontsize=8)
    axes[1].plot(x, profiles["T_wall"], lw=0.8, label="T_wall (CFD, all wetted faces)")
    axes[1].plot(x, profiles["T_bulk"], lw=1.2, label="T_bulk (energy balance)")
    axes[1].set_xlabel("x / D")
    axes[1].set_ylabel("T [K]")
    axes[1].set_title("Wall and bulk temperature")
    axes[1].grid(alpha=0.3)
    axes[1].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)
    return path
