#!/usr/bin/env python3
"""Daily Doer — local dashboard and todo manager.

Run:  python app.py  [--port 8780]
Then open http://localhost:8780
"""

from __future__ import annotations

import argparse
import faulthandler
import json
import logging
import re
import signal
import sys
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import db
import voice_board
import voice_edit
import voice_parser

APP_DIR = Path(__file__).parent
LOG_PATH = APP_DIR / "dailydoer.log"
SERVER = None
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def json_response(handler: BaseHTTPRequestHandler, status: int, payload: object) -> None:
    body = json.dumps(payload, default=str).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def html_response(handler: BaseHTTPRequestHandler, html: str) -> None:
    body = html.encode("utf-8")
    handler.send_response(200)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def read_json(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", 0))
    if length == 0:
        return {}
    raw = handler.rfile.read(length)
    try:
        data = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("JSON body must be an object")
    return data


def validate_due_date(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    if not ISO_DATE.match(value):
        raise ValueError("due_date must be YYYY-MM-DD")
    date.fromisoformat(value)
    return value


FONTS_LINK = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link href="https://fonts.googleapis.com/css2?family=Rajdhani:wght@400;500;600;700'
    '&family=Share+Tech+Mono&display=swap" rel="stylesheet">'
)

BASE_CSS = """
  :root {
    --bg: #030508;
    --panel: rgba(6, 14, 24, 0.88);
    --panel2: rgba(10, 22, 38, 0.92);
    --text: #e8f4ff;
    --muted: #6b8299;
    --cyan: #00d4ff;
    --cyan-dim: rgba(0, 212, 255, 0.35);
    --accent: #00d4ff;
    --urgent: #ff3344;
    --high: #ff9a3c;
    --ok: #00ff88;
    --backlog: #8ba4bc;
    --todo: #4dc9ff;
    --progress: #b388ff;
    --done: #00ff88;
    --line: rgba(0, 212, 255, 0.18);
    --glow: rgba(0, 212, 255, 0.45);
    --gold: #ffc832;
    --gold-dim: rgba(255, 200, 50, 0.35);
  }
  * { box-sizing: border-box; margin: 0; }
  html, body { min-height: 100%; }
  body {
    background: var(--bg);
    color: var(--text);
    font: 15px/1.45 "Rajdhani", "Segoe UI", sans-serif;
    letter-spacing: 0.02em;
  }
  .hud-bg {
    position: fixed; inset: 0; z-index: 0; pointer-events: none;
    background:
      radial-gradient(circle at 18% 12%, rgba(0, 212, 255, 0.08), transparent 34%),
      radial-gradient(circle at 82% 78%, rgba(255, 51, 68, 0.05), transparent 30%),
      radial-gradient(ellipse at 50% 100%, rgba(0, 80, 120, 0.18), transparent 55%),
      linear-gradient(180deg, #020408 0%, #071018 45%, #030508 100%);
  }
  .hud-gridlines {
    position: fixed; inset: 0; z-index: 0; pointer-events: none; opacity: 0.35;
    background-image:
      linear-gradient(rgba(0, 212, 255, 0.04) 1px, transparent 1px),
      linear-gradient(90deg, rgba(0, 212, 255, 0.04) 1px, transparent 1px);
    background-size: 48px 48px;
  }
  .hud-ring {
    position: fixed; left: 50%; top: 54%; width: min(90vw, 900px); aspect-ratio: 1;
    transform: translate(-50%, -50%); z-index: 0; pointer-events: none; opacity: 0.12;
    border: 1px solid var(--cyan-dim);
    border-radius: 50%;
    box-shadow: 0 0 0 40px rgba(0, 212, 255, 0.02), 0 0 120px rgba(0, 212, 255, 0.06);
  }
  .command-shell {
    position: relative; z-index: 1;
    max-width: 1600px; margin: 0 auto;
    padding: 16px 18px 48px;
  }
  .cmd-header {
    display: grid; grid-template-columns: 1fr auto; gap: 12px 20px;
    align-items: center; margin-bottom: 18px;
    padding-bottom: 14px;
    border-bottom: 1px solid var(--line);
  }
  .cmd-header-actions {
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
    justify-content: flex-end;
  }
  #voiceMasterBtn {
    min-width: 140px;
    font-size: 12px;
    font-weight: 700;
    padding: 10px 18px;
  }
  @media (max-width: 900px) { .cmd-header { grid-template-columns: 1fr; } }
  .cmd-brand { display: flex; flex-direction: column; gap: 4px; }
  .cmd-op {
    font-size: 26px; font-weight: 700; letter-spacing: 0.18em;
    text-transform: uppercase; color: var(--text);
    text-shadow: 0 0 24px rgba(0, 212, 255, 0.35);
  }
  .cmd-op span { color: var(--cyan); }
  .cmd-sub {
    font-family: "Share Tech Mono", Consolas, monospace;
    font-size: 12px; color: var(--muted); letter-spacing: 0.08em;
  }
  .cmd-nav {
    display: flex; gap: 6px; flex-wrap: wrap;
  }
  .cmd-nav a {
    color: var(--muted); text-decoration: none; font-size: 12px;
    font-weight: 600; letter-spacing: 0.16em; text-transform: uppercase;
    padding: 8px 14px; border: 1px solid transparent;
    transition: color .15s, border-color .15s, box-shadow .15s;
  }
  .cmd-nav a:hover { color: var(--cyan); border-color: var(--cyan-dim); }
  .cmd-nav a.active {
    color: var(--cyan); border-color: var(--cyan);
    box-shadow: 0 0 12px rgba(0, 212, 255, 0.25), inset 0 0 12px rgba(0, 212, 255, 0.06);
  }
  .cmd-ticker-wrap {
    grid-column: 1 / -1;
    border: 1px solid var(--line);
    background: rgba(0, 212, 255, 0.03);
    padding: 7px 12px; overflow: hidden;
    position: relative;
  }
  .cmd-ticker-wrap::before, .cmd-ticker-wrap::after {
    content: ""; position: absolute; top: 4px; width: 10px; height: 10px;
    border-color: var(--cyan); border-style: solid;
  }
  .cmd-ticker-wrap::before { left: 4px; border-width: 2px 0 0 2px; }
  .cmd-ticker-wrap::after { right: 4px; border-width: 2px 2px 0 0; }
  .cmd-ticker {
    font-family: "Share Tech Mono", monospace; font-size: 11px;
    color: var(--cyan); letter-spacing: 0.06em; white-space: nowrap;
    animation: ticker 28s linear infinite;
  }
  @keyframes ticker { from { transform: translateX(0); } to { transform: translateX(-50%); } }
  .cmd-layout {
    display: grid; grid-template-columns: 280px 1fr 240px; gap: 14px; align-items: start;
  }
  @media (max-width: 1200px) { .cmd-layout { grid-template-columns: 1fr; } }
  .cmd-side-right { display: flex; flex-direction: column; gap: 14px; }
  @media (max-width: 1200px) { .cmd-side-right { display: none; } }
  .hud-panel {
    position: relative;
    background: var(--panel);
    border: 1px solid var(--line);
    padding: 14px 16px; margin-bottom: 14px;
    box-shadow: inset 0 0 40px rgba(0, 212, 255, 0.02);
  }
  .hud-panel::before, .hud-panel::after {
    content: ""; position: absolute; width: 12px; height: 12px;
    border: 2px solid var(--cyan); opacity: 0.7;
  }
  .hud-panel::before { top: -1px; left: -1px; border-right: none; border-bottom: none; }
  .hud-panel::after { bottom: -1px; right: -1px; border-left: none; border-top: none; }
  .hud-title {
    font-size: 11px; font-weight: 700; letter-spacing: 0.2em;
    text-transform: uppercase; color: var(--cyan); margin-bottom: 12px;
    padding-bottom: 8px; border-bottom: 1px solid var(--line);
    display: flex; justify-content: space-between; align-items: center; gap: 8px;
  }
  .hud-title .count-pill {
    font-family: "Share Tech Mono", monospace; font-size: 11px;
    color: var(--text); letter-spacing: 0.05em;
    border: 1px solid var(--line); padding: 1px 8px; background: rgba(0,0,0,0.25);
  }
  .meter { margin-bottom: 12px; }
  .meter:last-child { margin-bottom: 0; }
  .meter-head {
    display: flex; justify-content: space-between; align-items: baseline;
    font-size: 12px; letter-spacing: 0.12em; text-transform: uppercase;
    color: var(--muted); margin-bottom: 5px;
  }
  .meter-val {
    font-family: "Share Tech Mono", monospace; color: var(--cyan); font-size: 13px;
  }
  .meter-track {
    height: 4px; background: rgba(0, 212, 255, 0.08);
    border: 1px solid rgba(0, 212, 255, 0.12);
  }
  .meter-fill {
    height: 100%; background: linear-gradient(90deg, rgba(0,212,255,0.5), var(--cyan));
    box-shadow: 0 0 10px var(--glow);
    transition: width .4s ease;
  }
  .meter-fill.alert {
    background: linear-gradient(90deg, rgba(255,51,68,0.5), var(--urgent));
    box-shadow: 0 0 10px rgba(255, 51, 68, 0.45);
  }
  .readout {
    display: flex; justify-content: space-between; align-items: center;
    padding: 10px 0; border-bottom: 1px solid rgba(255,255,255,0.04);
    font-size: 13px; letter-spacing: 0.08em; text-transform: uppercase;
  }
  .readout:last-child { border-bottom: none; }
  .readout .val {
    font-family: "Share Tech Mono", monospace; font-size: 20px; color: var(--cyan);
    text-shadow: 0 0 12px rgba(0, 212, 255, 0.35);
  }
  .readout .val.alert { color: var(--urgent); text-shadow: 0 0 12px rgba(255, 51, 68, 0.35); }
  .hex-btn {
    display: flex; flex-direction: column; align-items: center; gap: 8px;
    padding: 18px 12px; text-align: center; cursor: pointer;
    background: rgba(0, 212, 255, 0.04);
    border: 1px solid var(--cyan-dim);
    clip-path: polygon(10% 0, 90% 0, 100% 50%, 90% 100%, 10% 100%, 0 50%);
    transition: box-shadow .2s, background .2s;
  }
  .hex-btn:hover {
    background: rgba(0, 212, 255, 0.1);
    box-shadow: 0 0 20px rgba(0, 212, 255, 0.25);
  }
  .hex-btn.on {
    background: rgba(0, 212, 255, 0.14);
    border-color: var(--cyan);
    box-shadow: 0 0 24px rgba(0, 212, 255, 0.4);
  }
  .hex-btn.off {
    border-color: rgba(255, 154, 60, 0.55);
    background: rgba(255, 154, 60, 0.06);
  }
  .hex-btn.off .label { color: var(--high); }
  .hex-btn .dot {
    width: 10px; height: 10px; border-radius: 50%;
    background: var(--muted);
  }
  .hex-btn.on .dot {
    background: var(--cyan);
    animation: pulse 1.2s infinite;
  }
  .hex-btn .label { font-size: 11px; letter-spacing: 0.18em; color: var(--cyan); }
  .hex-btn.on .label { color: var(--cyan); text-shadow: 0 0 8px rgba(0, 212, 255, 0.5); }
  .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
  @media (max-width: 900px) { .grid-2 { grid-template-columns: 1fr; } }
  .section-head { display: flex; justify-content: space-between; align-items: center; gap: 10px; }
  .todo-list { display: flex; flex-direction: column; gap: 8px; }
  .todo-item {
    display: flex; align-items: flex-start; gap: 10px; padding: 10px 12px;
    background: var(--panel2); border: 1px solid rgba(0, 212, 255, 0.12);
    cursor: pointer; transition: border-color .15s, box-shadow .15s;
  }
  .todo-item:hover {
    border-color: var(--cyan-dim);
    box-shadow: 0 0 14px rgba(0, 212, 255, 0.12);
  }
  .todo-item.threat { border-left: 3px solid var(--urgent); }
  .todo-item .body { flex: 1; min-width: 0; }
  .todo-item .title { font-weight: 600; font-size: 15px; word-break: break-word; }
  .todo-item .meta {
    color: var(--muted); font-size: 11px; margin-top: 5px;
    font-family: "Share Tech Mono", monospace; letter-spacing: 0.04em;
  }
  .badge, .status-tag {
    display: inline-block; padding: 1px 7px; font-size: 10px; font-weight: 700;
    letter-spacing: 0.12em; text-transform: uppercase; margin-right: 6px;
    border: 1px solid currentColor;
  }
  .badge.urgent, .status-tag.threat { color: var(--urgent); background: rgba(255,51,68,0.1); box-shadow: 0 0 8px rgba(255,51,68,0.2); }
  .badge.high { color: var(--high); background: rgba(255,154,60,0.1); }
  .badge.normal { color: var(--todo); background: rgba(77,201,255,0.08); }
  .badge.low { color: var(--muted); background: rgba(139,164,188,0.08); }
  .badge.backlog { color: var(--backlog); background: rgba(139,164,188,0.08); }
  .badge.todo { color: var(--todo); background: rgba(77,201,255,0.08); }
  .badge.in_progress { color: var(--progress); background: rgba(179,136,255,0.1); }
  .badge.done, .status-tag.secure { color: var(--ok); background: rgba(0,255,136,0.08); box-shadow: 0 0 8px rgba(0,255,136,0.15); }
  .empty {
    padding: 20px; text-align: center; color: var(--muted); font-size: 12px;
    letter-spacing: 0.1em; text-transform: uppercase;
  }
  input, select, textarea {
    background: rgba(0, 0, 0, 0.35); color: var(--text);
    border: 1px solid var(--line); padding: 9px 12px;
    font: 14px "Rajdhani", sans-serif; letter-spacing: 0.04em;
    outline: none; width: 100%;
  }
  input:focus, select:focus, textarea:focus {
    border-color: var(--cyan);
    box-shadow: 0 0 0 1px rgba(0, 212, 255, 0.25);
  }
  textarea { resize: vertical; min-height: 72px; }
  button {
    background: rgba(0, 212, 255, 0.06); color: var(--text);
    border: 1px solid var(--line); padding: 8px 16px; cursor: pointer;
    font: 600 12px "Rajdhani", sans-serif; letter-spacing: 0.14em; text-transform: uppercase;
    transition: border-color .15s, box-shadow .15s, background .15s;
  }
  button:hover:not(:disabled) {
    border-color: var(--cyan); box-shadow: 0 0 12px rgba(0, 212, 255, 0.2);
  }
  button:disabled { opacity: .35; cursor: default; }
  button.primary {
    background: rgba(0, 212, 255, 0.15); border-color: var(--cyan);
    color: var(--cyan); text-shadow: 0 0 8px rgba(0, 212, 255, 0.4);
  }
  button.danger { border-color: rgba(255,51,68,0.5); color: #ff8a96; }
  button.danger:hover { border-color: var(--urgent); color: var(--urgent); }
  .form-row { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 10px; }
  .form-row > * { flex: 1; min-width: 140px; }
  .date-field { display: flex; flex-direction: column; gap: 4px; flex: 1; min-width: 160px; }
  .date-label { font-size: 11px; color: var(--muted); letter-spacing: 0.08em; text-transform: uppercase; }
  input[type="date"] {
    color-scheme: dark;
    cursor: pointer;
    min-height: 38px;
  }
  input[type="date"]::-webkit-calendar-picker-indicator {
    cursor: pointer;
    filter: invert(0.85);
    opacity: 0.95;
  }
  .quick-add { display: flex; gap: 10px; flex-wrap: wrap; }
  .quick-add input { flex: 2; min-width: 200px; }
  .quick-add select { flex: 0 0 120px; width: auto; }
  .quick-add input[type=date] { flex: 0 0 150px; width: auto; }
  .todo-hero-panel {
    position: relative;
    overflow: hidden;
    border-color: rgba(0, 212, 255, 0.55);
    box-shadow:
      0 0 22px rgba(0, 212, 255, 0.24),
      0 0 44px rgba(77, 201, 255, 0.1),
      inset 0 0 28px rgba(0, 212, 255, 0.07);
    animation: todoGlow 3s ease-in-out infinite;
  }
  .todo-hero-panel::after {
    content: '';
    position: absolute;
    inset: 0;
    pointer-events: none;
    background: linear-gradient(
      105deg,
      transparent 38%,
      rgba(0, 212, 255, 0.14) 50%,
      transparent 62%
    );
    background-size: 220% 100%;
    animation: todoShine 5s linear infinite;
  }
  @keyframes todoGlow {
    0%, 100% {
      box-shadow:
        0 0 18px rgba(0, 212, 255, 0.2),
        inset 0 0 18px rgba(0, 212, 255, 0.05);
      border-color: rgba(0, 212, 255, 0.45);
    }
    50% {
      box-shadow:
        0 0 34px rgba(0, 212, 255, 0.38),
        0 0 64px rgba(77, 201, 255, 0.16),
        inset 0 0 32px rgba(0, 212, 255, 0.12);
      border-color: rgba(0, 212, 255, 0.75);
    }
  }
  @keyframes todoShine {
    0% { background-position: 220% 0; }
    100% { background-position: -220% 0; }
  }
  .todo-hero-title {
    color: var(--cyan);
    text-shadow: 0 0 12px rgba(0, 212, 255, 0.45);
  }
  .todo-hero-tag {
    display: inline-block;
    font-size: 9px;
    padding: 2px 7px;
    margin-left: 8px;
    border: 1px solid var(--cyan);
    color: var(--cyan);
    letter-spacing: 0.14em;
    vertical-align: middle;
    box-shadow: 0 0 10px rgba(0, 212, 255, 0.25);
  }
  .todo-hero-panel .quick-add input#qaTitle {
    border-color: rgba(0, 212, 255, 0.5);
    box-shadow: 0 0 14px rgba(0, 212, 255, 0.18);
    background: rgba(0, 212, 255, 0.06);
  }
  .todo-hero-panel .quick-add input#qaTitle:focus {
    border-color: var(--cyan);
    box-shadow: 0 0 20px rgba(0, 212, 255, 0.35);
  }
  .grid-today-focus {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 14px;
  }
  .grid-today-focus .today-hero-panel { grid-column: 1 / -1; }
  .today-hero-panel {
    position: relative;
    overflow: hidden;
    border-color: rgba(255, 154, 60, 0.65);
    box-shadow:
      0 0 26px rgba(255, 154, 60, 0.28),
      0 0 52px rgba(255, 120, 40, 0.12),
      inset 0 0 32px rgba(255, 154, 60, 0.08);
    animation: todayFrameGlow 2.8s ease-in-out infinite;
  }
  .today-hero-panel::after {
    content: '';
    position: absolute;
    inset: 0;
    pointer-events: none;
    background: linear-gradient(
      115deg,
      transparent 35%,
      rgba(255, 180, 80, 0.16) 50%,
      transparent 65%
    );
    background-size: 240% 100%;
    animation: todayShine 4.5s linear infinite;
  }
  @keyframes todayFrameGlow {
    0%, 100% {
      border-color: rgba(255, 154, 60, 0.5);
      box-shadow:
        0 0 20px rgba(255, 154, 60, 0.22),
        inset 0 0 22px rgba(255, 154, 60, 0.06);
    }
    50% {
      border-color: rgba(255, 180, 90, 0.85);
      box-shadow:
        0 0 38px rgba(255, 154, 60, 0.42),
        0 0 72px rgba(255, 120, 40, 0.18),
        inset 0 0 36px rgba(255, 154, 60, 0.14);
    }
  }
  @keyframes todayShine {
    0% { background-position: 240% 0; }
    100% { background-position: -240% 0; }
  }
  .today-hero-title {
    color: #ffb86a;
    text-shadow: 0 0 14px rgba(255, 154, 60, 0.5);
  }
  .today-hero-tag {
    display: inline-block;
    font-size: 9px;
    padding: 2px 7px;
    margin-left: 8px;
    border: 1px solid #ff9a3c;
    color: #ffb86a;
    letter-spacing: 0.14em;
    vertical-align: middle;
    box-shadow: 0 0 12px rgba(255, 154, 60, 0.35);
    animation: todayTagPulse 2.8s ease-in-out infinite;
  }
  @keyframes todayTagPulse {
    0%, 100% { box-shadow: 0 0 8px rgba(255, 154, 60, 0.25); }
    50% { box-shadow: 0 0 16px rgba(255, 154, 60, 0.55); }
  }
  .today-hero-panel .todo-item.today-item {
    border-color: rgba(255, 154, 60, 0.35);
    background: rgba(255, 154, 60, 0.07);
    box-shadow: 0 0 12px rgba(255, 154, 60, 0.12);
  }
  .today-hero-panel .todo-item.today-item:hover {
    border-color: rgba(255, 180, 90, 0.75);
    box-shadow: 0 0 22px rgba(255, 154, 60, 0.28);
    background: rgba(255, 154, 60, 0.11);
  }
  .today-hero-panel .todo-item.today-item .title {
    color: #ffe8d0;
    text-shadow: 0 0 8px rgba(255, 154, 60, 0.2);
  }
  .today-hero-panel .empty {
    color: #ffb86a;
    text-shadow: 0 0 10px rgba(255, 154, 60, 0.25);
  }
  .msg { font-family: "Share Tech Mono", monospace; font-size: 11px; margin-top: 8px; min-height: 18px; }
  .msg.ok { color: var(--ok); }
  .msg.err { color: var(--urgent); }
  .kanban { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; align-items: start; }
  @media (max-width: 1100px) { .kanban { grid-template-columns: repeat(2, 1fr); } }
  @media (max-width: 600px) { .kanban { grid-template-columns: 1fr; } }
  .col {
    background: var(--panel); border: 1px solid var(--line);
    min-height: 220px; display: flex; flex-direction: column;
  }
  .col-head {
    padding: 10px 12px; border-bottom: 1px solid var(--line);
    font-size: 11px; font-weight: 700; letter-spacing: 0.18em; text-transform: uppercase;
    display: flex; justify-content: space-between; font-family: "Share Tech Mono", monospace;
  }
  .col-head.backlog { color: var(--backlog); }
  .col-head.todo { color: var(--todo); }
  .col-head.in_progress { color: var(--progress); }
  .col-head.done { color: var(--done); }
  .col-body {
    padding: 10px; flex: 1; display: flex; flex-direction: column; gap: 8px; min-height: 120px;
  }
  .col-body.drag-over {
    background: rgba(0, 212, 255, 0.05);
    outline: 1px dashed var(--cyan); outline-offset: -4px;
  }
  .kcard {
    background: var(--panel2); border: 1px solid rgba(0, 212, 255, 0.12);
    padding: 10px 12px; cursor: grab;
  }
  .kcard:active { cursor: grabbing; }
  .kcard.dragging { opacity: .4; }
  .kcard .title { font-weight: 600; word-break: break-word; margin-bottom: 6px; }
  .kcard .foot { display: flex; flex-wrap: wrap; gap: 4px; align-items: center; }
  .kcard .due { color: var(--muted); font-size: 10px; font-family: "Share Tech Mono", monospace; }
  .modal-bg {
    position: fixed; inset: 0; background: rgba(2, 4, 8, 0.82);
    backdrop-filter: blur(4px); display: none;
    align-items: center; justify-content: center; z-index: 50; padding: 20px;
  }
  .modal-bg.open { display: flex; }
  .modal {
    background: var(--panel); border: 1px solid var(--cyan-dim);
    padding: 20px; width: 100%; max-width: 480px; max-height: 90vh; overflow: auto;
    box-shadow: 0 0 40px rgba(0, 212, 255, 0.12);
  }
  .modal h2 {
    font-size: 14px; letter-spacing: 0.2em; text-transform: uppercase;
    color: var(--cyan); margin-bottom: 14px;
  }
  .modal-actions { display: flex; gap: 10px; justify-content: flex-end; margin-top: 16px; flex-wrap: wrap; }
  .toolbar { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 16px; align-items: center; }
  .toolbar input { flex: 1; min-width: 200px; width: auto; }
  .voice-status-hint {
    color: var(--muted);
    font-size: 11px;
    letter-spacing: 0.06em;
    margin-top: 6px;
  }
  .toolbar .voice-status-hint {
    margin-top: 0;
    flex: 1;
    min-width: 180px;
  }
  .nav-status {
    font-size: 11px;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--muted);
    padding: 4px 10px;
    border: 1px solid var(--line);
  }
  .nav-status.on {
    color: var(--cyan);
    border-color: var(--cyan-dim);
    box-shadow: 0 0 10px rgba(0, 212, 255, 0.2);
  }
  .btn-voice.voice-master-btn {
    letter-spacing: 0.12em;
    text-transform: uppercase;
    font-size: 12px;
    font-weight: 700;
    padding: 10px 18px;
    flex-shrink: 0;
    min-width: 130px;
    z-index: 2;
    border-color: var(--high);
    color: var(--high);
    background: rgba(255, 154, 60, 0.08);
  }
  .btn-voice.voice-master-btn.on {
    border-color: var(--cyan);
    color: var(--cyan);
    background: rgba(0, 212, 255, 0.12);
    box-shadow: 0 0 14px rgba(0, 212, 255, 0.35);
  }
  .btn-voice.voice-master-btn.on .dot {
    background: var(--cyan);
    animation: pulse 1.2s infinite;
  }
  .btn-voice.voice-master-btn.off {
    border-color: var(--high);
    color: var(--high);
    background: rgba(255, 154, 60, 0.08);
  }
  .btn-voice { display: inline-flex; align-items: center; gap: 8px; min-width: auto; }
  .btn-voice .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--muted); }
  .btn-voice.listening { border-color: var(--urgent); color: var(--urgent); box-shadow: 0 0 12px rgba(255,51,68,0.25); }
  .btn-voice.listening .dot { background: var(--urgent); animation: pulse 1s infinite; }
  @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: .35; } }
  .voice-modal { max-width: 560px; }
  .voice-log {
    background: rgba(0,0,0,0.35); border: 1px solid var(--line);
    padding: 12px; max-height: 220px; overflow: auto; margin-bottom: 14px;
    display: flex; flex-direction: column; gap: 10px;
  }
  .voice-line { font-size: 13px; line-height: 1.45; }
  .voice-line.user { color: var(--text); }
  .voice-line.app { color: var(--cyan); }
  .voice-line .who {
    color: var(--muted); font-size: 10px; text-transform: uppercase;
    letter-spacing: 0.14em; display: block; margin-bottom: 2px;
  }
  .voice-preview {
    background: rgba(0,0,0,0.35); border: 1px solid var(--line);
    padding: 12px; margin-bottom: 14px; font-size: 13px;
  }
  .voice-preview .row { display: flex; gap: 8px; margin-bottom: 6px; }
  .voice-preview .lbl { color: var(--muted); min-width: 72px; letter-spacing: 0.1em; text-transform: uppercase; font-size: 11px; }
  .voice-preview .val { flex: 1; word-break: break-word; font-family: "Share Tech Mono", monospace; }
  .voice-controls { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
  .voice-controls input { flex: 1; min-width: 180px; width: auto; }
  .voice-hint { color: var(--muted); font-size: 11px; margin-top: 10px; letter-spacing: 0.04em; }
  .voice-date-row {
    display: none;
    gap: 10px;
    align-items: flex-end;
    margin: 10px 0 4px;
    flex-wrap: wrap;
  }
  .voice-date-row .date-field { min-width: 180px; }
  .voice-date-row button { flex: 0 0 auto; min-width: auto; }
  .sub { color: var(--muted); margin: 0 0 14px; font-size: 12px; letter-spacing: 0.06em; }
"""

VOICE_MODAL_HTML = """
<div class="modal-bg" id="voiceModal">
  <div class="modal voice-modal hud-panel">
    <h2>// Voice uplink</h2>
    <p class="sub" id="voiceSub">Speak mission objectives. System parses fields and requests missing intel.</p>
    <div class="voice-log" id="voiceLog"></div>
    <div class="voice-preview" id="voicePreview">
      <div class="row"><span class="lbl">Title</span><span class="val" id="vpTitle">—</span></div>
      <div class="row"><span class="lbl">Due</span><span class="val" id="vpDue">—</span></div>
      <div class="row"><span class="lbl">Priority</span><span class="val" id="vpPriority">—</span></div>
      <div class="row"><span class="lbl">Status</span><span class="val" id="vpStatus">—</span></div>
    </div>
    <div class="voice-date-row" id="voiceDueRow">
      <label class="date-field">
        <span class="date-label">Due date</span>
        <input id="voiceDuePick" type="date">
      </label>
      <button type="button" id="voiceDueApply">Use date</button>
    </div>
    <div class="voice-controls">
      <button class="btn-voice" id="voiceMicBtn" type="button"><span class="dot"></span> Open channel</button>
      <input id="voiceText" type="text" placeholder="Manual input channel…">
      <button id="voiceSendBtn" type="button">Transmit</button>
    </div>
    <div class="msg" id="voiceMsg"></div>
    <div class="modal-actions">
      <button id="voiceCancelBtn" type="button">Abort</button>
      <button class="primary" id="voiceSaveBtn" type="button" disabled>Confirm objective</button>
    </div>
    <p class="voice-hint" id="voiceHint">Interrupt by speaking. Say "done with task" to confirm, or 10s silence auto-saves.</p>
  </div>
</div>
"""

VOICE_JS = """
const VoiceUI = (() => {
  const PRIORITY_LABELS = {low:'Low', normal:'Normal', high:'High', urgent:'Urgent'};
  const STATUS_LABELS = {backlog:'Backlog', todo:'To Do', in_progress:'In Progress', done:'Done'};
  let recognition = null;
  let listening = false;
  let voiceState = null;
  let pendingField = null;
  let ready = false;
  let onCreated = null;
  let lastDraft = null;
  let saving = false;
  const IDLE_MS = 10000;
  let lastSpeechAt = 0;
  let silenceChecker = null;
  let speaking = false;
  let mode = 'create';
  let boardPending = null;
  let boardConfirm = null;
  let createConfirm = null;
  let boardSubMode = 'command';
  let boardProcessing = false;
  let boardSpeaking = false;
  let lastBoardTranscript = '';
  let lastBoardTranscriptAt = 0;
  let wakeRecognition = null;
  let wakeEnabled = false;
  let wakeOnOpen = null;
  let wakeVoiceMode = 'board';
  let editSession = null;
  let editSaveConfirm = null;
  let boardUi = null;
  let queuedWakeCommand = null;
  const VOICE_TAB_KEY = 'dailydoer.tabSession';
  const VOICE_STATE_KEY = 'dailydoer.voiceMaster';

  function bootstrapVoiceSession() {
    try {
      if (!sessionStorage.getItem(VOICE_TAB_KEY)) {
        sessionStorage.setItem(VOICE_TAB_KEY, String(Date.now()));
        localStorage.removeItem(VOICE_STATE_KEY);
        if (sessionStorage.getItem(VOICE_STATE_KEY) !== '1') {
          sessionStorage.removeItem(VOICE_STATE_KEY);
        }
      }
    } catch (_) {}
  }

  function readVoiceMasterSession() {
    try {
      if (!sessionStorage.getItem(VOICE_TAB_KEY)) return false;
      if (sessionStorage.getItem(VOICE_STATE_KEY) === '1') return true;
      if (localStorage.getItem(VOICE_STATE_KEY) === '1') return true;
      return false;
    } catch (_) {
      return false;
    }
  }

  function writeVoiceMasterSession(on) {
    try {
      if (!sessionStorage.getItem(VOICE_TAB_KEY)) {
        sessionStorage.setItem(VOICE_TAB_KEY, String(Date.now()));
      }
      const val = on ? '1' : '0';
      sessionStorage.setItem(VOICE_STATE_KEY, val);
      if (on) localStorage.setItem(VOICE_STATE_KEY, '1');
      else localStorage.removeItem(VOICE_STATE_KEY);
    } catch (_) {}
  }

  bootstrapVoiceSession();
  let voiceMasterOn = readVoiceMasterSession();

  function isStartNavigation(text) {
    const n = normalizeExitText(text);
    return n === 'start navigation';
  }

  function isStopNavigation(text) {
    const n = normalizeExitText(text);
    return n === 'stop navigation';
  }

  function updateVoiceMasterUi() {
    document.querySelectorAll('.voice-master-btn').forEach(btn => {
      btn.classList.toggle('on', voiceMasterOn);
      btn.classList.toggle('off', !voiceMasterOn);
      btn.setAttribute('aria-pressed', voiceMasterOn ? 'true' : 'false');
      btn.title = voiceMasterOn ? 'Voice is ON — click to turn off' : 'Voice is OFF — click to turn on';
      const label = btn.querySelector('.voice-master-label');
      if (label) {
        label.textContent = voiceMasterOn ? 'Voice ON' : 'Voice OFF';
      }
    });
    document.querySelectorAll('.voice-status-hint').forEach(el => {
      el.textContent = voiceMasterOn
        ? 'Voice ON — stays on until you click Voice OFF (persists across pages)'
        : 'Voice OFF — click Voice OFF at the top right to enable for this session';
    });
  }

  function wireNavPersistVoice() {
    document.querySelectorAll('.cmd-nav a[href]').forEach(link => {
      link.addEventListener('click', () => {
        writeVoiceMasterSession(voiceMasterOn);
      }, true);
    });
  }

  function wireVoiceMasterButton() {
    const btn = document.getElementById('voiceMasterBtn');
    if (!btn) return;
    btn.classList.add('voice-master-btn');
    btn.onclick = () => toggleVoiceMaster();
    updateVoiceMasterUi();
  }

  function applyVoiceMasterState(on) {
    voiceMasterOn = !!on;
    wakeEnabled = voiceMasterOn;
    updateVoiceMasterUi();
    if (voiceMasterOn) {
      startWakeListen();
    } else {
      stopWakeListen();
      queuedWakeCommand = null;
      if (document.getElementById('voiceModal').classList.contains('open')) close();
    }
  }

  function setVoiceMaster(on) {
    const next = !!on;
    writeVoiceMasterSession(next);
    applyVoiceMasterState(next);
  }

  function toggleVoiceMaster() {
    setVoiceMaster(!voiceMasterOn);
    navFeedback(voiceMasterOn ? 'Voice on.' : 'Voice off.');
  }

  function setNavEnabled(on) {
    setVoiceMaster(on);
  }

  function registerBoardUi(hooks) {
    boardUi = hooks || null;
  }

  function voiceCommandsAllowed() {
    return voiceMasterOn;
  }

  function promptStartNavigation() {
    boardNotify('Turn on voice with the Voice OFF button at the top right.');
  }

  function navFeedback(text) {
    if (!window.speechSynthesis || !text) return;
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(new SpeechSynthesisUtterance(text));
  }

  function isModalVoiceMode() {
    return mode === 'board' || mode === 'dashboard';
  }

  const EXIT_RE = /^(?:exit(?:\\s+voice(?:\\s+mode)?)?|close(?:\\s+voice)?|quit(?:\\s+voice)?)\\.?$/i;

  const DONE_RE = /^(?:done|that(?:'?s| is)?(?:\\s+it|\\s+all)?|save(?:\\s+it)?|create(?:\\s+it)?|finish|go ahead|submit|stop)\\.?$/i;

  function normalizeExitText(text) {
    return (text || '').trim().replace(/[.!?,;]+$/, '').toLowerCase()
      .replace(/[''`´]/g, '')
      .replace(/\\s+/g, ' ')
      .trim();
  }

  function isExitVoiceMode(text) {
    const t = (text || '').trim().replace(/[.!?]+$/, '');
    const n = normalizeExitText(text);
    if (!n) return false;
    if (EXIT_RE.test(t)) return true;
    if (/exit\\s+voice\\s+mode/.test(n)) return true;
    if (n === 'thats it' || n === 'that is it') return true;
    if (n === 'thats all' || n === 'that is all') return true;
    if (n === 'finish' || n === 'close') return true;
    return false;
  }

  function isStartVoiceMode(text) {
    const t = (text || '').trim().toLowerCase().replace(/[.!?,;]+$/, '');
    return /(?:start|open|begin)(?:\\s+up)?\\s+voice\\s+mode/.test(t) ||
      /(?:start|open)\\s+voice(?:\\s+mode)?/.test(t);
  }

  function parseNavigateTarget(text) {
    const n = (text || '').trim().toLowerCase().replace(/[.!?,;]+$/, '').replace(/\\s+/g, ' ');
    const m = n.match(/^(?:move|switch|go)\\s+(?:to\\s+)?(?:the\\s+)?(.+)$/);
    if (!m) return null;
    const dest = m[1].trim();
    if (/^(?:dashboard|command center|home|main page|main)$/.test(dest)) return '/';
    if (/^(?:task board|taskboard|tasks board|tasks|kanban|board|todos|to do list|to-do list)$/.test(dest)) {
      return '/todos';
    }
    return null;
  }

  function handleNavigateCommand(text) {
    if (!voiceMasterOn) return false;
    const path = parseNavigateTarget(text);
    if (!path) return false;
    const here = location.pathname.replace(/\\/+$/, '') || '/';
    if (here === path) {
      if (document.getElementById('voiceModal')?.classList.contains('open')) {
        boardNotify('Already on this page.');
      }
      return true;
    }
    close();
    location.href = path;
    return true;
  }

  function handleNavToggle(heard) {
    if (isStartNavigation(heard)) {
      setVoiceMaster(true);
      navFeedback('Voice on.');
      return true;
    }
    if (isStopNavigation(heard)) {
      setVoiceMaster(false);
      navFeedback('Voice off.');
      return true;
    }
    return false;
  }

  function openVoiceModalFromWake() {
    if (wakeVoiceMode === 'board') openBoard(wakeOnOpen);
    else openDashboard(wakeOnOpen);
  }

  function handleWakePhrase(heard) {
    if (!heard) return false;
    if (handleNavToggle(heard)) return true;
    if (!voiceMasterOn) return false;
    if (handleNavigateCommand(heard)) return true;
    if (wakeOnOpen && !document.getElementById('voiceModal').classList.contains('open')) {
      if (isStartVoiceMode(heard)) {
        openVoiceModalFromWake();
        return true;
      }
      if (isCreateCommand(heard) || isBareCreateCommand(heard) ||
          isEditCommand(heard) || isBareEditCommand(heard)) {
        queuedWakeCommand = heard;
        openVoiceModalFromWake();
        return true;
      }
    }
    return false;
  }

  function normalizeBoardText(text) {
    return (text || '').trim().replace(/[.!?,;]+$/, '');
  }

  function isYes(text) {
    const t = normalizeBoardText(text).toLowerCase();
    return /^(?:yes|yeah|yep|yup|confirm|do it|go ahead|ok|okay|sure|affirmative|please|proceed|ready|correct)$/i.test(t);
  }

  function isNo(text) {
    const t = normalizeBoardText(text).toLowerCase();
    return /^(?:no|nope|nah|cancel|cancelled|never mind|nevermind|stop|negative|dont|don't)$/i.test(t);
  }

  function isConfirming() {
    return !!(boardConfirm || createConfirm || editSaveConfirm);
  }

  function isDuplicateBoardTranscript(text) {
    const t = normalizeBoardText(text).toLowerCase();
    if (!t) return true;
    if (t === lastBoardTranscript && (Date.now() - lastBoardTranscriptAt) < 2500) return true;
    lastBoardTranscript = t;
    lastBoardTranscriptAt = Date.now();
    return false;
  }

  function isBareCreateCommand(text) {
    const n = normalizeExitText(text);
    return /^(?:add|create|new)(?:\\s+(?:a|an))?\\s*(?:task|todo|objective)s?$/.test(n) ||
      n === 'create' || n === 'new task' || n === 'new objective' ||
      /^new\\s+objective$/.test(n);
  }

  function isCreateCommand(text) {
    const t = (text || '').trim();
    if (!t) return false;
    if (isBareCreateCommand(t)) return true;
    return /^(?:add|create|new)\\s+(?:a\\s+)?(?:task|todo|objective)/i.test(t) ||
      /^new\\s+objective\\b/i.test(t) ||
      /^(?:remind me to|remember to|i need to|i should|i have to)/i.test(t);
  }

  function isBareEditCommand(text) {
    const n = normalizeExitText(text);
    return n === 'edit' || n === 'edit task' || n === 'update task' || n === 'change task';
  }

  function isEditCommand(text) {
    const t = (text || '').trim();
    if (!t) return false;
    if (isBareEditCommand(t)) return true;
    return /^(?:edit|update|change)\\s+(?:the\\s+)?(?:task\\s+)?\\S/i.test(t);
  }

  function syncBoardFormFromEdit(session) {
    if (!boardUi || !boardUi.syncEditFields || !session) return;
    const merged = Object.assign({}, session.todo, session.changes || {});
    boardUi.syncEditFields(merged);
  }

  function syncBoardFormFromCreate(draft) {
    if (!boardUi || !boardUi.syncCreateFields || !draft) return;
    boardUi.syncCreateFields(draft);
  }

  function beginBoardCreate() {
    voiceState = null;
    pendingField = null;
    editSession = null;
    editSaveConfirm = null;
    setBoardCreateUi(true);
    if (boardUi && boardUi.openNew) boardUi.openNew('todo');
  }

  function isDoneCommand(text) {
    const t = (text || '').trim().replace(/[.!?]+$/, '');
    if (!t) return false;
    if (DONE_RE.test(t)) return true;
    return /^(?:i'?m\\s+)?done\\s+with(?:\\s+(?:the\\s+)?)?(?:task|this|it)?$/i.test(t);
  }

  function stopSpeaking() {
    speaking = false;
    if (window.speechSynthesis) window.speechSynthesis.cancel();
  }

  function clearSilenceWatch() {
    if (silenceChecker) {
      clearInterval(silenceChecker);
      silenceChecker = null;
    }
  }

  function bumpSpeechActivity() {
    lastSpeechAt = Date.now();
  }

  function startSilenceWatch() {
    if (isModalVoiceMode()) return;
    clearSilenceWatch();
    bumpSpeechActivity();
    silenceChecker = setInterval(() => {
      if (!document.getElementById('voiceModal').classList.contains('open')) return;
      if (Date.now() - lastSpeechAt >= IDLE_MS) {
        clearSilenceWatch();
        saveTodo('silence');
      }
    }, 500);
  }

  function esc(s) {
    return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  function setMode(next) {
    mode = next;
    const preview = document.getElementById('voicePreview');
    const saveBtn = document.getElementById('voiceSaveBtn');
    const sub = document.getElementById('voiceSub');
    const hint = document.getElementById('voiceHint');
    if (next === 'board') {
      preview.style.display = 'none';
      saveBtn.style.display = 'none';
      sub.textContent = 'Voice commands for the task board.';
      hint.textContent = 'Say new objective, create task, edit, move, or delete. Say exit voice mode to close.';
    } else if (next === 'dashboard') {
      preview.style.display = 'none';
      saveBtn.style.display = 'none';
      sub.textContent = 'Voice on dashboard — create or edit tasks.';
      hint.textContent = 'Create: add task… Edit: edit buy milk, set priority to urgent, set due date to tomorrow, save. Say exit voice mode to close.';
    } else {
      preview.style.display = '';
      saveBtn.style.display = '';
      sub.textContent = 'Speak mission objectives. System parses fields and requests missing intel.';
      hint.textContent = 'Say move to task board or switch to dashboard.';
    }
  }

  function setBoardCreateUi(on) {
    boardSubMode = on ? 'create' : (editSession ? 'edit' : 'command');
    document.getElementById('voicePreview').style.display = (on || editSession) ? '' : 'none';
    if (!on && !editSession) document.getElementById('voiceDueRow').style.display = 'none';
  }

  function setEditPreview(session) {
    if (!session) return;
    const merged = Object.assign({}, session.todo, session.changes || {});
    updatePreview({
      title: merged.title,
      priority: merged.priority,
      due_date: merged.due_date,
      status: merged.status,
    });
    document.getElementById('voicePreview').style.display = '';
  }

  function boardNotify(text) {
    logLine('Daily Doer', text);
    const msg = document.getElementById('voiceMsg');
    msg.className = 'msg';
    msg.textContent = text;
  }

  function boardSpeakThenListen(text) {
    stopListening();
    boardSpeaking = true;
    const done = () => {
      boardSpeaking = false;
      document.getElementById('voiceMsg').textContent = 'Listening…';
      if (queuedWakeCommand) {
        const cmd = queuedWakeCommand;
        queuedWakeCommand = null;
        setTimeout(() => submitTranscript(cmd), 150);
        return;
      }
      resumeBoardListening();
    };
    if (!text || !window.speechSynthesis) {
      done();
      return;
    }
    stopSpeaking();
    const u = new SpeechSynthesisUtterance(text);
    u.onend = done;
    u.onerror = done;
    window.speechSynthesis.speak(u);
  }

  function boardAskConfirm(message) {
    boardNotify(message);
    boardSpeakThenListen(message);
  }

  function boardDone() {
    boardConfirm = null;
    createConfirm = null;
    editSession = null;
    editSaveConfirm = null;
    boardPending = null;
    voiceState = null;
    pendingField = null;
    setBoardCreateUi(false);
    boardSpeakThenListen('Done.');
  }

  function resumeBoardListening() {
    if (!isModalVoiceMode()) return;
    if (boardProcessing || boardSpeaking) return;
    if (!document.getElementById('voiceModal').classList.contains('open')) return;
    setTimeout(() => {
      if (!boardProcessing && !boardSpeaking && document.getElementById('voiceModal').classList.contains('open')) {
        startListening();
      }
    }, 200);
  }

  function stopWakeListen() {
    if (wakeRecognition) {
      try { wakeRecognition.stop(); } catch (_) {}
    }
  }

  function startWakeListen() {
    if (!wakeEnabled) return;
    if (document.getElementById('voiceModal').classList.contains('open')) return;
    const Ctor = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Ctor) return;
    if (!wakeRecognition) {
      wakeRecognition = new Ctor();
      wakeRecognition.continuous = false;
      wakeRecognition.interimResults = false;
      wakeRecognition.lang = 'en-US';
      wakeRecognition.onresult = (event) => {
        let finalText = '';
        for (let i = event.resultIndex; i < event.results.length; i++) {
          if (event.results[i].isFinal) finalText += event.results[i][0].transcript;
        }
        const heard = finalText.trim();
        if (heard) handleWakePhrase(heard);
      };
      wakeRecognition.onend = () => {
        if (wakeEnabled && !document.getElementById('voiceModal').classList.contains('open')) {
          setTimeout(() => startWakeListen(), 400);
        }
      };
      wakeRecognition.onerror = (event) => {
        if (event.error === 'aborted') return;
        if (wakeEnabled && !document.getElementById('voiceModal').classList.contains('open')) {
          setTimeout(() => startWakeListen(), 600);
        }
      };
    }
    try {
      wakeRecognition.start();
    } catch (_) {}
  }

  function initPageVoice(cb, voiceMode) {
    wakeOnOpen = cb;
    wakeVoiceMode = voiceMode || 'board';
    wireVoiceMasterButton();
    wireNavPersistVoice();
    applyVoiceMasterState(readVoiceMasterSession());
  }

  function enablePageWake(cb, voiceMode) {
    initPageVoice(cb, voiceMode);
  }

  function enableBoardWake(cb) {
    initPageVoice(cb, 'board');
  }

  function enableDashboardWake(cb) {
    initPageVoice(cb, 'dashboard');
  }

  function disableBoardWake() {
    setVoiceMaster(false);
  }

  function clearBoardDebounce() {}

  async function executeEditSave() {
    if (!editSaveConfirm) return false;
    const res = await fetch('/api/voice/edit', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({execute_save: editSaveConfirm}),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) {
      boardNotify(data.message || data.error || 'Could not save changes.');
      return false;
    }
    editSaveConfirm = null;
    editSession = null;
    setBoardCreateUi(false);
    if (boardUi && boardUi.closeModal) boardUi.closeModal();
    if (onCreated) await onCreated();
    boardNotify(data.message);
    return true;
  }

  async function submitEditCommand(text) {
    const res = await fetch('/api/voice/edit', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        transcript: text,
        edit_session: editSession,
        awaiting_save: editSaveConfirm,
      }),
    });
    const data = await res.json();
    if (!res.ok) {
      boardNotify(data.error || data.message || 'Could not parse that.');
      return;
    }
    if (data.needs_save_confirm && data.awaiting_save) {
      editSaveConfirm = data.awaiting_save;
      editSession = data.awaiting_save;
      boardAskConfirm(data.message);
      return;
    }
    if (data.save && data.ok) {
      editSaveConfirm = data.edit_session || editSaveConfirm;
      await executeEditSave();
      return;
    }
    if (data.cancelled) {
      editSaveConfirm = null;
      boardNotify(data.message);
      return;
    }
    if (data.edit_session) {
      editSession = data.edit_session;
      setEditPreview(editSession);
      setBoardCreateUi(false);
      if (boardUi && boardUi.openEdit && editSession.todo && editSession.todo.id) {
        boardUi.openEdit(editSession.todo.id);
      }
      syncBoardFormFromEdit(editSession);
      boardNotify(data.message);
      return;
    }
    boardNotify(data.message || 'Try again.');
  }

  async function handleCreateCommand(trimmed) {
    if (isBareCreateCommand(trimmed)) {
      beginBoardCreate();
      boardNotify('What should I call the new objective?');
      return;
    }
    if (boardSubMode !== 'create') beginBoardCreate();
    await submitBoardCreate(trimmed);
  }

  async function handleEditCommand(trimmed) {
    if (isBareEditCommand(trimmed)) {
      boardNotify('Say edit and the task name — for example, edit buy milk.');
      return;
    }
    await submitEditCommand(trimmed);
  }

  async function submitDashboardTranscript(text) {
    const trimmed = (text || '').trim();
    if (!trimmed || isDuplicateBoardTranscript(trimmed)) return;

    boardProcessing = true;
    stopListening();
    logLine('You', trimmed);
    document.getElementById('voiceText').value = '';

    try {
      if (isExitVoiceMode(trimmed)) { close(); return; }
      if (handleNavToggle(trimmed)) return;
      if (!voiceCommandsAllowed()) { promptStartNavigation(); return; }
      if (handleNavigateCommand(trimmed)) return;

      if (editSaveConfirm) {
        await handleBoardConfirmAnswer(trimmed);
        return;
      }
      if (boardConfirm || createConfirm) {
        await handleBoardConfirmAnswer(trimmed);
        return;
      }
      if (isYes(trimmed) || isNo(trimmed)) {
        boardNotify('Nothing to confirm.');
        return;
      }

      if (boardSubMode === 'create' || isCreateCommand(trimmed)) {
        await handleCreateCommand(trimmed);
        return;
      }

      if (editSession || isEditCommand(trimmed)) {
        await handleEditCommand(trimmed);
        return;
      }

      boardNotify('Say add task, edit task name, move, or delete.');
    } finally {
      boardProcessing = false;
      if (!isConfirming() && !boardSpeaking) resumeBoardListening();
    }
  }

  async function executeBoardCreate() {
    const msg = document.getElementById('voiceMsg');
    msg.className = 'msg';
    if (!createConfirm) return false;

    const body = {
      title: createConfirm.title,
      description: createConfirm.description || '',
      priority: createConfirm.priority || 'normal',
      status: createConfirm.status || 'todo',
      due_date: createConfirm.due_date || null,
    };
    const pending = createConfirm;
    const res = await fetch('/api/todos', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) {
      createConfirm = pending;
      msg.textContent = data.error || 'Could not create task.';
      msg.classList.add('err');
      boardNotify(msg.textContent);
      return false;
    }

    createConfirm = null;
    voiceState = null;
    pendingField = null;
    lastDraft = null;
    setBoardCreateUi(false);
    if (boardUi && boardUi.closeModal) boardUi.closeModal();

    if (onCreated) await onCreated();
    boardNotify('Task created.');
    return true;
  }

  async function submitBoardCreate(text) {
    const res = await fetch('/api/voice/parse', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        transcript: text,
        draft: voiceState,
        pending_field: pendingField,
      }),
    });
    const data = await res.json();
    if (!res.ok) {
      boardNotify(data.error || 'Could not parse that.');
      return;
    }

    voiceState = data.state;
    pendingField = data.pending_field;
    lastDraft = data.draft;
    setBoardCreateUi(true);
    updatePreview(data.draft);
    syncBoardFormFromCreate(data.draft);

    if (data.question) {
      boardNotify(data.question);
      document.getElementById('voiceDueRow').style.display =
        pendingField === 'due_date' ? 'flex' : 'none';
      return;
    }

    if (data.ready && data.draft && data.draft.title) {
      document.getElementById('voiceDueRow').style.display = 'none';
      createConfirm = data.draft;
      const duePart = data.draft.due_date ? (' due ' + fmtDue(data.draft.due_date)) : '';
      boardAskConfirm('Create ' + data.draft.title + duePart + '. Say yes or no.');
    }
  }

  async function executeBoardConfirm() {
    const msg = document.getElementById('voiceMsg');
    msg.className = 'msg';
    if (!boardConfirm) return false;

    const pending = boardConfirm;
    const res = await fetch('/api/voice/board', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({execute_confirm: pending}),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) {
      boardConfirm = pending;
      msg.textContent = data.error || data.message || 'Could not complete that action.';
      msg.classList.add('err');
      boardNotify(msg.textContent);
      return false;
    }

    boardConfirm = null;
    boardPending = null;
    if (onCreated) await onCreated();
    boardNotify(data.message);
    return true;
  }

  async function handleBoardConfirmAnswer(trimmed) {
    if (editSaveConfirm) {
      if (isYes(trimmed)) {
        const ok = await executeEditSave();
        if (ok) boardDone();
        return;
      }
      if (isNo(trimmed)) {
        editSaveConfirm = null;
        boardNotify('Changes not saved.');
        return;
      }
      boardAskConfirm('Say yes or no.');
      return;
    }
    if (isYes(trimmed)) {
      const ok = boardConfirm
        ? await executeBoardConfirm()
        : await executeBoardCreate();
      if (ok) boardDone();
      return;
    }
    if (isNo(trimmed)) {
      boardConfirm = null;
      createConfirm = null;
      boardPending = null;
      voiceState = null;
      pendingField = null;
      setBoardCreateUi(false);
      boardNotify('Cancelled.');
      boardSpeakThenListen('Cancelled.');
      return;
    }
    boardNotify('Say yes or no.');
    boardSpeakThenListen('Say yes or no.');
  }

  async function submitBoardTranscript(text) {
    const msg = document.getElementById('voiceMsg');
    msg.className = 'msg';
    const trimmed = (text || '').trim();
    if (!trimmed) return;
    if (isDuplicateBoardTranscript(trimmed)) return;

    boardProcessing = true;
    stopListening();
    bumpSpeechActivity();
    logLine('You', trimmed);
    document.getElementById('voiceText').value = '';

    try {
      if (isExitVoiceMode(trimmed)) {
        close();
        return;
      }

      if (handleNavToggle(trimmed)) return;

      if (!voiceCommandsAllowed()) {
        promptStartNavigation();
        return;
      }

      if (handleNavigateCommand(trimmed)) {
        return;
      }

      if (boardConfirm || createConfirm || editSaveConfirm) {
        await handleBoardConfirmAnswer(trimmed);
        return;
      }

      if (isYes(trimmed) || isNo(trimmed)) {
        boardNotify('Nothing to confirm.');
        return;
      }

      if (boardSubMode === 'create' || isCreateCommand(trimmed)) {
        await handleCreateCommand(trimmed);
        return;
      }

      if (editSession || isEditCommand(trimmed)) {
        await handleEditCommand(trimmed);
        return;
      }

      const res = await fetch('/api/voice/board', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({transcript: trimmed, pending: boardPending}),
      });
      let data;
      try {
        data = await res.json();
      } catch (_) {
        msg.textContent = 'Server response error.';
        msg.classList.add('err');
        boardNotify(msg.textContent);
        return;
      }

      if (!res.ok) {
        msg.textContent = data.error || data.message || 'Could not parse that command.';
        msg.classList.add('err');
        boardNotify(msg.textContent);
        return;
      }

      if (!data.ok) {
        boardPending = data.pending || null;
        boardNotify(data.message);
        return;
      }

      if (data.needs_confirm && data.confirm) {
        boardPending = null;
        boardConfirm = data.confirm;
        boardAskConfirm(data.message);
        return;
      }

      if (data.cancelled || data.info) {
        boardPending = null;
        boardNotify(data.message);
        return;
      }

      boardPending = null;
      boardNotify(data.message || 'Try again.');
    } finally {
      boardProcessing = false;
      if (!isConfirming() && !boardSpeaking) {
        resumeBoardListening();
      }
    }
  }

  async function saveTodo(reason) {
    if (saving) return;
    clearSilenceWatch();
    stopListening();
    stopSpeaking();

    let draft = lastDraft;
    if (voiceState) {
      const res = await fetch('/api/voice/finalize', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ draft: voiceState }),
      });
      const data = await res.json();
      if (res.ok && data.draft) draft = data.draft;
    }

    const msg = document.getElementById('voiceMsg');
    msg.className = 'msg';
    if (!draft || !draft.title) {
      if (reason === 'silence') {
        logLine('Daily Doer', 'Still waiting for a todo title…');
        startSilenceWatch();
        startListening();
        return;
      }
      msg.textContent = 'Title is still missing.';
      msg.classList.add('err');
      startSilenceWatch();
      return;
    }

    saving = true;
    const body = {
      title: draft.title,
      description: draft.description || '',
      priority: draft.priority || 'normal',
      status: draft.status || 'todo',
      due_date: draft.due_date || null,
    };
    const res = await fetch('/api/todos', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    });
    const data = await res.json();
    saving = false;
    if (!res.ok) {
      msg.textContent = data.error || 'Could not create todo.';
      msg.classList.add('err');
      startSilenceWatch();
      return;
    }
    if (reason === 'done') {
      logLine('Daily Doer', 'Saved your todo.');
    } else if (reason === 'silence') {
      logLine('Daily Doer', 'Saved after 10 seconds of silence.');
    }
    close();
    if (onCreated) onCreated(data);
  }

  function fmtDue(iso) {
    if (!iso) return 'No due date';
    const d = new Date(iso + 'T12:00:00');
    return d.toLocaleDateString(undefined, {weekday:'short', month:'short', day:'numeric'});
  }

  function logLine(who, text) {
    const el = document.getElementById('voiceLog');
    const div = document.createElement('div');
    div.className = 'voice-line ' + (who === 'You' ? 'user' : 'app');
    div.innerHTML = '<span class="who">' + esc(who) + '</span>' + esc(text);
    el.appendChild(div);
    el.scrollTop = el.scrollHeight;
  }

  function updatePreview(draft) {
    document.getElementById('vpTitle').textContent = draft.title || '—';
    document.getElementById('vpDue').textContent = draft.due_date ? fmtDue(draft.due_date) : (voiceState && voiceState.due_date_declined ? 'No due date' : '—');
    document.getElementById('vpPriority').textContent = draft.priority ? (PRIORITY_LABELS[draft.priority] || draft.priority) : '—';
    document.getElementById('vpStatus').textContent = draft.status ? (STATUS_LABELS[draft.status] || draft.status) : '—';
    document.getElementById('voiceSaveBtn').disabled = !(draft && draft.title);
  }

  function setListening(on) {
    listening = on;
    const btn = document.getElementById('voiceMicBtn');
    btn.classList.toggle('listening', on);
    btn.innerHTML = on
      ? '<span class="dot"></span> Channel open…'
      : '<span class="dot"></span> Open channel';
  }

  function speak(text, autoListen) {
    if (isModalVoiceMode()) {
      if (autoListen) resumeBoardListening();
      return;
    }
    stopSpeaking();
    if (!window.speechSynthesis || !text) {
      if (autoListen) startListening();
      return;
    }
    speaking = true;
    const u = new SpeechSynthesisUtterance(text);
    u.onend = () => {
      speaking = false;
      if (autoListen) startListening();
    };
    u.onerror = () => {
      speaking = false;
      if (autoListen) startListening();
    };
    window.speechSynthesis.speak(u);
  }

  async function submitTranscript(text) {
    const msg = document.getElementById('voiceMsg');
    msg.className = 'msg';
    const trimmed = (text || '').trim();
    if (!trimmed) return;

    bumpSpeechActivity();

    if (isExitVoiceMode(trimmed)) {
      logLine('You', trimmed);
      document.getElementById('voiceText').value = '';
      close();
      return;
    }

    if (handleNavToggle(trimmed)) {
      logLine('You', trimmed);
      document.getElementById('voiceText').value = '';
      return;
    }

    if (handleNavigateCommand(trimmed)) {
      logLine('You', trimmed);
      document.getElementById('voiceText').value = '';
      return;
    }

    if (isDoneCommand(trimmed)) {
      logLine('You', trimmed);
      document.getElementById('voiceText').value = '';
      if (mode === 'board') {
        close();
        return;
      }
      await saveTodo('done');
      return;
    }

    if (mode === 'board') {
      await submitBoardTranscript(trimmed);
      return;
    }

    if (mode === 'dashboard') {
      await submitDashboardTranscript(trimmed);
      return;
    }

    logLine('You', trimmed);
    document.getElementById('voiceText').value = '';

    const res = await fetch('/api/voice/parse', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        transcript: trimmed,
        draft: voiceState,
        pending_field: pendingField,
      }),
    });
    const data = await res.json();
    if (!res.ok) {
      msg.textContent = data.error || 'Could not parse that.';
      msg.classList.add('err');
      startSilenceWatch();
      return;
    }

    voiceState = data.state;
    pendingField = data.pending_field;
    ready = !!data.ready;
    lastDraft = data.draft;
    updatePreview(data.draft);

    if (data.question) {
      logLine('Daily Doer', data.question);
      speak(data.question, true);
      startSilenceWatch();
    } else if (ready) {
      logLine('Daily Doer', 'Got it — saving your todo.');
      await saveTodo('ready');
    } else {
      startSilenceWatch();
    }
  }

  function ensureRecognition() {
    const Ctor = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Ctor) return null;
    if (!recognition) {
      recognition = new Ctor();
      recognition.continuous = false;
      recognition.interimResults = true;
      recognition.lang = 'en-US';
      recognition.onresult = (event) => {
        bumpSpeechActivity();
        let interim = '';
        let finalText = '';
        for (let i = event.resultIndex; i < event.results.length; i++) {
          const part = event.results[i][0].transcript;
          if (event.results[i].isFinal) finalText += part;
          else interim += part;
        }
        const heard = (finalText || interim).trim();
        document.getElementById('voiceText').value = heard;

        if (mode === 'board' || mode === 'dashboard') {
          if (boardProcessing) return;
          if (boardSpeaking && !isConfirming()) {
            if (finalText.trim()) {
              stopSpeaking();
              boardSpeaking = false;
            } else {
              return;
            }
          }
          if (finalText.trim()) {
            submitTranscript(finalText.trim());
          }
          return;
        }

        if (speaking && heard) stopSpeaking();

        if (finalText.trim()) {
          stopListening();
          submitTranscript(finalText.trim());
        }
      };
      recognition.onend = () => {
        setListening(false);
        resumeBoardListening();
      };
      recognition.onerror = (event) => {
        if (event.error === 'aborted' || event.error === 'no-speech') {
          resumeBoardListening();
          return;
        }
        setListening(false);
        if (mode === 'board' || mode === 'dashboard') {
          resumeBoardListening();
          return;
        }
        const msg = document.getElementById('voiceMsg');
        msg.textContent = 'Speech error: ' + event.error;
        msg.classList.add('err');
      };
    }
    return recognition;
  }

  function startListening() {
    const msg = document.getElementById('voiceMsg');
    msg.className = 'msg';
    const rec = ensureRecognition();
    if (!rec) {
      msg.textContent = 'Speech recognition is not supported in this browser. Type your answers instead.';
      msg.classList.add('err');
      return;
    }
    try {
      rec.continuous = false;
      rec.interimResults = true;
      rec.start();
      setListening(true);
      if (!isModalVoiceMode()) startSilenceWatch();
    } catch (_) {
      if (mode === 'board') resumeBoardListening();
    }
  }

  function stopListening() {
    if (recognition) {
      try { recognition.stop(); } catch (_) {}
    }
    setListening(false);
  }

  function reset() {
    voiceState = null;
    pendingField = null;
    ready = false;
    lastDraft = null;
    saving = false;
    boardPending = null;
    boardConfirm = null;
    createConfirm = null;
    editSession = null;
    editSaveConfirm = null;
    boardSubMode = 'command';
    boardProcessing = false;
    boardSpeaking = false;
    lastBoardTranscript = '';
    lastBoardTranscriptAt = 0;
    clearBoardDebounce();
    clearSilenceWatch();
    document.getElementById('voiceDueRow').style.display = 'none';
    document.getElementById('voiceDuePick').value = '';
    document.getElementById('voiceLog').innerHTML = '';
    document.getElementById('voiceText').value = '';
    document.getElementById('voiceMsg').className = 'msg';
    document.getElementById('voiceMsg').textContent = '';
    updatePreview({title:null, due_date:null, priority:null, status:null});
    stopListening();
  }

  function open(cb) {
    onCreated = cb;
    reset();
    setMode('create');
    document.getElementById('voiceModal').classList.add('open');
    logLine('Daily Doer', 'Tell me the todo — for example: "Urgent call dentist tomorrow" or "Remind me to buy milk".');
    speak('What todo should I add?', true);
    startSilenceWatch();
  }

  function openDashboard(cb) {
    if (!voiceMasterOn) {
      navFeedback('Turn on voice first.');
      return;
    }
    stopWakeListen();
    onCreated = cb;
    reset();
    setMode('dashboard');
    document.getElementById('voiceModal').classList.add('open');
    logLine('Daily Doer', 'Ready.');
    boardSpeakThenListen('Ready.');
  }

  function openBoard(cb) {
    if (!voiceMasterOn) {
      navFeedback('Turn on voice first.');
      return;
    }
    stopWakeListen();
    onCreated = cb;
    reset();
    setMode('board');
    document.getElementById('voiceModal').classList.add('open');
    logLine('Daily Doer', 'Ready.');
    boardSpeakThenListen('Ready.');
  }

  function close() {
    document.getElementById('voiceModal').classList.remove('open');
    clearSilenceWatch();
    clearBoardDebounce();
    boardConfirm = null;
    boardPending = null;
    createConfirm = null;
    boardSubMode = 'command';
    boardProcessing = false;
    boardSpeaking = false;
    lastBoardTranscript = '';
    lastBoardTranscriptAt = 0;
    setBoardCreateUi(false);
    document.getElementById('voiceDueRow').style.display = 'none';
    document.getElementById('voiceDuePick').value = '';
    editSession = null;
    editSaveConfirm = null;
    stopListening();
    stopSpeaking();
    if (wakeEnabled) startWakeListen();
  }

  function bind() {
    updateVoiceMasterUi();
    window.addEventListener('pageshow', (event) => {
      if (event.persisted) applyVoiceMasterState(readVoiceMasterSession());
    });
    document.getElementById('voiceMicBtn').onclick = () => {
      if (listening) stopListening();
      else startListening();
    };
    document.getElementById('voiceSendBtn').onclick = () => {
      bumpSpeechActivity();
      submitTranscript(document.getElementById('voiceText').value);
    };
    document.getElementById('voiceText').addEventListener('input', bumpSpeechActivity);
    document.getElementById('voiceText').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') document.getElementById('voiceSendBtn').click();
    });
    document.getElementById('voiceCancelBtn').onclick = close;
    document.getElementById('voiceModal').onclick = (e) => {
      if (e.target.id === 'voiceModal') close();
    };
    document.getElementById('voiceSaveBtn').onclick = () => saveTodo('manual');
    document.getElementById('voiceDueApply').onclick = () => {
      const iso = document.getElementById('voiceDuePick').value;
      if (!iso) return;
      if (mode === 'board' && boardSubMode === 'create') {
        submitTranscript(iso);
      }
    };
  }

  return { bind, open, openBoard, openDashboard, initPageVoice, enablePageWake, enableBoardWake, enableDashboardWake, disableBoardWake, setVoiceMaster, toggleVoiceMaster, setNavEnabled, registerBoardUi, isVoiceMasterOn: () => voiceMasterOn };
})();
VoiceUI.bind();
"""

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Daily Doer — Command Center</title>
""" + FONTS_LINK + """
<style>""" + BASE_CSS + """</style>
</head>
<body>
<div class="hud-bg"></div>
<div class="hud-gridlines"></div>
<div class="hud-ring"></div>
<div class="command-shell">
  <header class="cmd-header">
    <div class="cmd-brand">
      <div class="cmd-op">Daily <span>Doer</span></div>
      <div class="cmd-sub" id="dateLine">INITIALIZING…</div>
    </div>
    <div class="cmd-header-actions">
      <nav class="cmd-nav">
        <a href="/" class="active">Dashboard</a>
        <a href="/todos">Task board</a>
      </nav>
      <button class="btn-voice voice-master-btn off" id="voiceMasterBtn" type="button" aria-pressed="false" title="Toggle voice mode for the whole app">
        <span class="dot"></span>
        <span class="voice-master-label">Voice OFF</span>
      </button>
    </div>
    <div class="cmd-ticker-wrap">
      <div class="cmd-ticker" id="statusTicker">SYSTEM STANDBY // AWAITING MISSION DATA //</div>
    </div>
  </header>
  <p class="voice-status-hint">Voice OFF — click Voice OFF at the top right to enable</p>

  <div class="cmd-layout">
    <aside class="cmd-side-left">
      <section class="hud-panel">
        <div class="hud-title">Ops status</div>
        <div id="statMeters"></div>
      </section>
      <section class="hud-panel todo-hero-panel">
        <div class="hud-title todo-hero-title">Quick deploy <span class="todo-hero-tag">To-do</span></div>
        <div class="quick-add">
          <input id="qaTitle" type="text" placeholder="Objective title…" maxlength="200">
          <select id="qaPriority">
            <option value="normal">Normal</option>
            <option value="high">High</option>
            <option value="urgent">Urgent</option>
            <option value="low">Low</option>
          </select>
          <label class="date-field" style="flex:0 0 160px">
            <span class="date-label">Due date</span>
            <input id="qaDue" type="date" title="Pick a due date">
          </label>
          <button class="primary" id="qaBtn">Deploy</button>
        </div>
        <div class="msg" id="qaMsg"></div>
      </section>
    </aside>

    <main class="cmd-main">
      <section class="hud-panel">
        <div class="hud-title">Priority threats <span class="count-pill" id="cntUrgent">0</span></div>
        <div class="todo-list" id="listUrgent"></div>
      </section>
      <div class="grid-2 grid-today-focus">
        <section class="hud-panel today-hero-panel">
          <div class="hud-title today-hero-title">Due today <span class="today-hero-tag">Do today</span> <span class="count-pill" id="cntToday">0</span></div>
          <div class="todo-list" id="listToday"></div>
        </section>
        <section class="hud-panel">
          <div class="hud-title">Due tomorrow <span class="count-pill" id="cntTomorrow">0</span></div>
          <div class="todo-list" id="listTomorrow"></div>
        </section>
      </div>
      <section class="hud-panel">
        <div class="hud-title">Rest of week <span class="count-pill" id="cntWeek">0</span></div>
        <div class="todo-list" id="listWeek"></div>
      </section>
    </main>

    <aside class="cmd-side-right">
      <section class="hud-panel">
        <div class="hud-title">Force readout</div>
        <div id="readoutPanel"></div>
      </section>
    </aside>
  </div>
</div>
""" + VOICE_MODAL_HTML + """
<script>
""" + VOICE_JS + """
VoiceUI.initPageVoice(() => loadDashboard(), 'dashboard');
const PRIORITY_LABELS = {low:'Low', normal:'Normal', high:'High', urgent:'Urgent'};
const STATUS_LABELS = {backlog:'Backlog', todo:'To Do', in_progress:'In Progress', done:'Done'};

function esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function fmtDate(iso) {
  if (!iso) return '';
  const d = new Date(iso + 'T12:00:00');
  return d.toLocaleDateString(undefined, {weekday:'short', month:'short', day:'numeric'});
}

function fmtMilDate(d) {
  const months = ['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC'];
  const dd = String(d.getDate()).padStart(2,'0');
  return `${dd}${months[d.getMonth()]}${d.getFullYear()}`;
}

function meter(label, value, max, alert) {
  const pct = max > 0 ? Math.min(100, Math.round((value / max) * 100)) : 0;
  const fillClass = alert ? 'meter-fill alert' : 'meter-fill';
  return `<div class="meter">
    <div class="meter-head"><span>${label}</span><span class="meter-val">${value}</span></div>
    <div class="meter-track"><div class="${fillClass}" style="width:${pct || (value ? 8 : 0)}%"></div></div>
  </div>`;
}

function renderItem(t, extraClass) {
  const pri = t.priority || 'normal';
  const due = t.due_date ? fmtDate(t.due_date) : 'NO DUE DATE';
  const st = STATUS_LABELS[t.status] || t.status;
  const threat = pri === 'urgent' || pri === 'high';
  const tag = pri === 'urgent' ? '<span class="status-tag threat">THREAT</span>' :
    pri === 'high' ? '<span class="status-tag threat">ELEVATED</span>' :
    '<span class="status-tag secure">TRACK</span>';
  const cls = 'todo-item' + (extraClass ? ' ' + extraClass : '') + (threat ? ' threat' : '');
  return `<div class="${cls}" data-id="${t.id}" onclick="location.href='/todos#edit-${t.id}'">
    <div class="body">
      <div class="title">${esc(t.title)}</div>
      <div class="meta">${tag}<span class="badge ${pri}">${PRIORITY_LABELS[pri]}</span><span class="badge ${t.status}">${esc(st)}</span>${esc(due)}</div>
    </div>
  </div>`;
}

function renderList(el, items, itemClass) {
  if (!items.length) {
    el.innerHTML = '<div class="empty">Sector clear — no objectives</div>';
    return;
  }
  el.innerHTML = items.map(t => renderItem(t, itemClass)).join('');
}

async function loadDashboard() {
  const res = await fetch('/api/dashboard');
  const data = await res.json();
  const today = new Date(data.today + 'T12:00:00');
  document.getElementById('dateLine').textContent =
    `OP DAY ${fmtMilDate(today)} // ${today.toLocaleDateString(undefined, {weekday:'long'})}`;

  const c = data.counts;
  const max = Math.max(c.active, c.urgent_high, c.due_today, c.due_tomorrow, c.due_this_week, c.backlog, 1);
  document.getElementById('statMeters').innerHTML =
    meter('Active objectives', c.active, max, false) +
    meter('Priority threats', c.urgent_high, max, c.urgent_high > 0) +
    meter('Due today', c.due_today, max, c.due_today > 0) +
    meter('Due tomorrow', c.due_tomorrow, max, false) +
    meter('Rest of week', c.due_this_week, max, false);

  document.getElementById('readoutPanel').innerHTML = `
    <div class="readout"><span>Active</span><span class="val">${c.active}</span></div>
    <div class="readout"><span>Threats</span><span class="val${c.urgent_high ? ' alert' : ''}">${c.urgent_high}</span></div>
    <div class="readout"><span>Today</span><span class="val">${c.due_today}</span></div>
    <div class="readout"><span>Backlog</span><span class="val">${c.backlog}</span></div>`;

  const alert = c.urgent_high > 0
    ? `ALERT: ${c.urgent_high} HIGH-PRIORITY OBJECTIVE(S) DETECTED — IMMEDIATE ACTION REQUIRED // `
    : `ALL SECTORS NOMINAL // ${c.active} ACTIVE OBJECTIVES TRACKED // `;
  document.getElementById('statusTicker').textContent = alert + alert + alert;

  document.getElementById('cntUrgent').textContent = c.urgent_high;
  document.getElementById('cntToday').textContent = c.due_today;
  document.getElementById('cntTomorrow').textContent = c.due_tomorrow;
  document.getElementById('cntWeek').textContent = c.due_this_week;

  renderList(document.getElementById('listUrgent'), data.urgent_high);
  renderList(document.getElementById('listToday'), data.due_today, 'today-item');
  renderList(document.getElementById('listTomorrow'), data.due_tomorrow);
  renderList(document.getElementById('listWeek'), data.due_this_week);
}

document.getElementById('qaBtn').onclick = async () => {
  const msg = document.getElementById('qaMsg');
  msg.className = 'msg';
  const title = document.getElementById('qaTitle').value.trim();
  if (!title) { msg.textContent = 'Enter a title.'; msg.classList.add('err'); return; }
  const body = {
    title,
    priority: document.getElementById('qaPriority').value,
    due_date: document.getElementById('qaDue').value || null,
    status: 'todo',
  };
  const res = await fetch('/api/todos', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
  const data = await res.json();
  if (!res.ok) { msg.textContent = data.error || 'Failed'; msg.classList.add('err'); return; }
  document.getElementById('qaTitle').value = '';
  document.getElementById('qaDue').value = '';
  msg.textContent = 'Added.';
  msg.classList.add('ok');
  loadDashboard();
};

document.getElementById('qaTitle').addEventListener('keydown', e => {
  if (e.key === 'Enter') document.getElementById('qaBtn').click();
});

loadDashboard();
</script>
</body>
</html>"""

TODOS_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Task Board — Daily Doer</title>
""" + FONTS_LINK + """
<style>""" + BASE_CSS + """</style>
</head>
<body>
<div class="hud-bg"></div>
<div class="hud-gridlines"></div>
<div class="hud-ring"></div>
<div class="command-shell">
  <header class="cmd-header">
    <div class="cmd-brand">
      <div class="cmd-op">Task <span>Board</span></div>
      <div class="cmd-sub">KANBAN // BACKLOG // DRAG-AND-DROP SECTORS</div>
    </div>
    <div class="cmd-header-actions">
      <nav class="cmd-nav">
        <a href="/">Dashboard</a>
        <a href="/todos" class="active">Task board</a>
      </nav>
      <button class="btn-voice voice-master-btn off" id="voiceMasterBtn" type="button" aria-pressed="false" title="Toggle voice mode for the whole app">
        <span class="dot"></span>
        <span class="voice-master-label">Voice OFF</span>
      </button>
    </div>
    <div class="cmd-ticker-wrap">
      <div class="cmd-ticker" id="statusTicker">MISSION CONTROL // DRAG OBJECTIVES BETWEEN SECTORS // LONG-RANGE ITEMS → BACKLOG //</div>
    </div>
  </header>

  <div class="toolbar">
    <input id="search" type="search" placeholder="Search objectives…">
    <button class="primary" id="newBtn">+ New objective</button>
    <span class="voice-status-hint">Voice OFF — click Voice OFF at the top right to enable</span>
  </div>

  <div class="kanban" id="kanban"></div>
</div>

""" + VOICE_MODAL_HTML + """

<div class="modal-bg" id="modal">
  <div class="modal hud-panel">
    <h2 id="modalTitle">New objective</h2>
    <div class="form-row">
      <input id="fTitle" type="text" placeholder="Title" maxlength="200">
    </div>
    <div class="form-row">
      <textarea id="fDesc" placeholder="Description (optional)"></textarea>
    </div>
    <div class="form-row">
      <select id="fPriority">
        <option value="low">Low</option>
        <option value="normal" selected>Normal</option>
        <option value="high">High</option>
        <option value="urgent">Urgent</option>
      </select>
      <select id="fStatus">
        <option value="backlog">Backlog</option>
        <option value="todo" selected>To Do</option>
        <option value="in_progress">In Progress</option>
        <option value="done">Done</option>
      </select>
      <label class="date-field">
        <span class="date-label">Due date</span>
        <input id="fDue" type="date" title="Pick a due date">
      </label>
    </div>
    <div class="msg" id="fMsg"></div>
    <div class="modal-actions">
      <button class="danger" id="delBtn" style="display:none;margin-right:auto">Delete</button>
      <button id="cancelBtn">Cancel</button>
      <button class="primary" id="saveBtn">Save</button>
    </div>
  </div>
</div>

<script>
""" + VOICE_JS + """
VoiceUI.initPageVoice(() => loadTodos(), 'board');
VoiceUI.registerBoardUi({
  openEdit(id) { openEdit(id); },
  openNew(status) { openNew(status || 'todo'); },
  closeModal() { closeModal(); },
  syncEditFields(merged) {
    if (!merged) return;
    document.getElementById('fTitle').value = merged.title || '';
    document.getElementById('fDesc').value = merged.description || '';
    document.getElementById('fPriority').value = merged.priority || 'normal';
    document.getElementById('fStatus').value = merged.status || 'todo';
    document.getElementById('fDue').value = merged.due_date || '';
  },
  syncCreateFields(draft) {
    if (!draft) return;
    if (draft.title) document.getElementById('fTitle').value = draft.title;
    if (draft.priority) document.getElementById('fPriority').value = draft.priority;
    if (draft.status) document.getElementById('fStatus').value = draft.status;
    if (draft.due_date) document.getElementById('fDue').value = draft.due_date;
    if (draft.description) document.getElementById('fDesc').value = draft.description;
  },
});
const STATUSES = ['backlog', 'todo', 'in_progress', 'done'];
const STATUS_LABELS = {backlog:'Backlog', todo:'To Do', in_progress:'In Progress', done:'Done'};
const PRIORITY_LABELS = {low:'Low', normal:'Normal', high:'High', urgent:'Urgent'};
let allTodos = [];
let editingId = null;
let dragId = null;

function esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function fmtDate(iso) {
  if (!iso) return '';
  const d = new Date(iso + 'T12:00:00');
  return d.toLocaleDateString(undefined, {month:'short', day:'numeric'});
}

function filtered() {
  const q = document.getElementById('search').value.trim().toLowerCase();
  if (!q) return allTodos;
  return allTodos.filter(t =>
    (t.title || '').toLowerCase().includes(q) ||
    (t.description || '').toLowerCase().includes(q));
}

function renderKanban() {
  const items = filtered();
  const byStatus = Object.fromEntries(STATUSES.map(s => [s, items.filter(t => t.status === s)]));
  const cols = STATUSES.map(status => {
    const cards = byStatus[status].map(t => {
      const pri = t.priority || 'normal';
      const due = t.due_date ? fmtDate(t.due_date) : '';
      return `<div class="kcard" draggable="true" data-id="${t.id}" data-status="${status}">
        <div class="title">${esc(t.title)}</div>
        <div class="foot">
          <span class="badge ${pri}">${PRIORITY_LABELS[pri]}</span>
          ${due ? `<span class="due">${esc(due)}</span>` : ''}
        </div>
      </div>`;
    }).join('');
    return `<div class="col" data-status="${status}">
      <div class="col-head ${status}">${STATUS_LABELS[status]}
        <span class="count-pill">${byStatus[status].length}</span></div>
      <div class="col-body" data-drop="${status}">${cards || '<div class="empty">Awaiting objectives</div>'}</div>
    </div>`;
  }).join('');
  document.getElementById('kanban').innerHTML = cols;
  bindDrag();
  bindCardClick();
}

function bindCardClick() {
  document.querySelectorAll('.kcard').forEach(el => {
    el.addEventListener('click', e => {
      if (el.classList.contains('dragging')) return;
      openEdit(parseInt(el.dataset.id, 10));
    });
  });
}

function bindDrag() {
  document.querySelectorAll('.kcard').forEach(card => {
    card.addEventListener('dragstart', e => {
      dragId = parseInt(card.dataset.id, 10);
      card.classList.add('dragging');
      e.dataTransfer.effectAllowed = 'move';
    });
    card.addEventListener('dragend', () => {
      card.classList.remove('dragging');
      dragId = null;
      document.querySelectorAll('.col-body').forEach(b => b.classList.remove('drag-over'));
    });
  });
  document.querySelectorAll('.col-body').forEach(body => {
    body.addEventListener('dragover', e => { e.preventDefault(); body.classList.add('drag-over'); });
    body.addEventListener('dragleave', () => body.classList.remove('drag-over'));
    body.addEventListener('drop', async e => {
      e.preventDefault();
      body.classList.remove('drag-over');
      if (!dragId) return;
      const status = body.dataset.drop;
      const res = await fetch(`/api/todos/${dragId}/move`, {
        method: 'PATCH',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({status}),
      });
      if (res.ok) loadTodos();
    });
  });
}

function openModal(isNew) {
  document.getElementById('modal').classList.add('open');
  document.getElementById('modalTitle').textContent = isNew ? 'New objective' : 'Edit objective';
  document.getElementById('delBtn').style.display = isNew ? 'none' : 'inline-block';
  document.getElementById('fMsg').className = 'msg';
  document.getElementById('fMsg').textContent = '';
}

function closeModal() {
  document.getElementById('modal').classList.remove('open');
  editingId = null;
}

function openNew(status) {
  editingId = null;
  document.getElementById('fTitle').value = '';
  document.getElementById('fDesc').value = '';
  document.getElementById('fPriority').value = 'normal';
  document.getElementById('fStatus').value = status || 'todo';
  document.getElementById('fDue').value = '';
  openModal(true);
}

function openEdit(id) {
  const t = allTodos.find(x => x.id === id);
  if (!t) return;
  editingId = id;
  document.getElementById('fTitle').value = t.title || '';
  document.getElementById('fDesc').value = t.description || '';
  document.getElementById('fPriority').value = t.priority || 'normal';
  document.getElementById('fStatus').value = t.status || 'todo';
  document.getElementById('fDue').value = t.due_date || '';
  openModal(false);
}

async function loadTodos() {
  const res = await fetch('/api/todos?include_done=1');
  allTodos = await res.json();
  renderKanban();
}

document.getElementById('newBtn').onclick = () => openNew('todo');
document.getElementById('cancelBtn').onclick = closeModal;
document.getElementById('modal').onclick = e => { if (e.target.id === 'modal') closeModal(); };

document.getElementById('saveBtn').onclick = async () => {
  const msg = document.getElementById('fMsg');
  msg.className = 'msg';
  const body = {
    title: document.getElementById('fTitle').value.trim(),
    description: document.getElementById('fDesc').value,
    priority: document.getElementById('fPriority').value,
    status: document.getElementById('fStatus').value,
    due_date: document.getElementById('fDue').value || null,
  };
  if (!body.title) { msg.textContent = 'Title is required.'; msg.classList.add('err'); return; }
  const url = editingId ? `/api/todos/${editingId}` : '/api/todos';
  const method = editingId ? 'PUT' : 'POST';
  const res = await fetch(url, {method, headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
  const data = await res.json();
  if (!res.ok) { msg.textContent = data.error || 'Save failed'; msg.classList.add('err'); return; }
  closeModal();
  loadTodos();
};

document.getElementById('delBtn').onclick = async () => {
  if (!editingId || !confirm('Delete this todo?')) return;
  const res = await fetch(`/api/todos/${editingId}`, {method:'DELETE'});
  if (res.ok) { closeModal(); loadTodos(); }
};

document.getElementById('search').oninput = renderKanban;

const hash = location.hash.match(/^#edit-(\\d+)$/);
loadTodos().then(() => {
  if (hash) openEdit(parseInt(hash[1], 10));
});
</script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:
        msg = f"[{self.log_date_time_string()}] {fmt % args}"
        print(msg, flush=True)
        logging.info(msg)

    def handle_one_request(self) -> None:
        try:
            super().handle_one_request()
        except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
            logging.debug("client disconnected")
        except Exception:
            logging.exception("unhandled request error")
            raise

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        qs = parse_qs(urlparse(self.path).query)

        try:
            if path == "/":
                html_response(self, DASHBOARD_HTML)
            elif path == "/todos":
                html_response(self, TODOS_HTML)
            elif path == "/api/dashboard":
                json_response(self, 200, db.dashboard_data())
            elif path == "/api/todos":
                status = qs.get("status", [None])[0]
                include_done = qs.get("include_done", ["0"])[0] in ("1", "true", "yes")
                todos = db.list_todos(status=status, include_done=include_done)
                json_response(self, 200, todos)
            elif path.startswith("/api/todos/"):
                suffix = path.rsplit("/", 1)[-1]
                if not suffix.isdigit():
                    json_response(self, 404, {"error": "not found"})
                    return
                todo_id = int(suffix)
                todo = db.get_todo(todo_id)
                if not todo:
                    json_response(self, 404, {"error": "not found"})
                else:
                    json_response(self, 200, todo)
            else:
                json_response(self, 404, {"error": "not found"})
        except Exception as exc:
            json_response(self, 500, {"error": str(exc)})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            if path == "/api/shutdown":
                logging.info("graceful shutdown requested")
                json_response(self, 200, {"ok": True})
                if SERVER is not None:
                    def _shutdown() -> None:
                        import time
                        time.sleep(0.05)
                        SERVER.shutdown()

                    threading.Thread(target=_shutdown, daemon=True).start()
                return
            if path == "/api/voice/board":
                data = read_json(self)
                confirm = data.get("execute_confirm")
                if confirm:
                    action = confirm.get("action")
                    todo = confirm.get("todo") or {}
                    todo_id = todo.get("id")
                    if not todo_id:
                        json_response(self, 400, {"ok": False, "error": "invalid confirm"})
                        return
                    if action == "move":
                        target = confirm.get("target_status")
                        if not target:
                            json_response(self, 400, {"ok": False, "error": "status required"})
                            return
                        updated = db.move_todo(todo_id, status=target)
                        if not updated:
                            json_response(self, 404, {"ok": False, "error": "task not found"})
                            return
                        result = voice_board.execute_confirm(confirm)
                    elif action == "delete":
                        if not db.delete_todo(todo_id):
                            json_response(self, 404, {"ok": False, "error": "task not found"})
                            return
                        result = voice_board.execute_confirm(confirm)
                    else:
                        json_response(self, 400, {"ok": False, "error": "unknown action"})
                        return
                    json_response(self, 200, result)
                    return

                transcript = data.get("transcript", "")
                pending = data.get("pending")
                awaiting = data.get("awaiting_confirm")
                todos = db.list_todos(include_done=True)
                result = voice_board.process_board_command(
                    transcript,
                    todos,
                    pending=pending,
                    awaiting_confirm=awaiting,
                )
                json_response(self, 200, result)
                return
            if path == "/api/voice/edit":
                data = read_json(self)
                execute = data.get("execute_save")
                if execute:
                    todo_id = (execute.get("todo") or {}).get("id")
                    changes = execute.get("changes") or {}
                    if not todo_id:
                        json_response(self, 400, {"ok": False, "error": "invalid session"})
                        return
                    if not changes:
                        json_response(self, 200, {"ok": True, "message": "No changes to save."})
                        return
                    todo = db.update_todo(todo_id, **changes)
                    if not todo:
                        json_response(self, 404, {"ok": False, "error": "task not found"})
                        return
                    json_response(self, 200, {"ok": True, "save": True, "message": "Changes saved.", "todo": todo})
                    return
                transcript = data.get("transcript", "")
                edit_session = data.get("edit_session")
                awaiting = data.get("awaiting_save")
                todos = db.list_todos(include_done=True)
                result = voice_edit.process_edit_command(
                    transcript,
                    todos,
                    edit_session=edit_session,
                    awaiting_save=awaiting,
                )
                json_response(self, 200, result)
                return
            if path == "/api/voice/finalize":
                data = read_json(self)
                finalized = voice_parser.finalize_for_save(data.get("draft"))
                if not finalized:
                    json_response(self, 400, {"error": "title is required"})
                else:
                    json_response(self, 200, {"draft": finalized})
                return
            if path == "/api/voice/parse":
                data = read_json(self)
                transcript = data.get("transcript", "")
                draft = data.get("draft")
                pending = data.get("pending_field")
                result = voice_parser.process_voice(
                    transcript,
                    draft=draft,
                    pending_field=pending,
                )
                state = voice_parser.state_from_response(result)
                payload = {
                    "draft": result["draft"],
                    "ready": result["ready"],
                    "pending_field": result["pending_field"],
                    "question": result["question"],
                    "transcript": result["transcript"],
                    "state": state,
                }
                json_response(self, 200, payload)
                return
            if path != "/api/todos":
                json_response(self, 404, {"error": "not found"})
                return
            data = read_json(self)
            due = validate_due_date(data.get("due_date"))
            todo = db.create_todo(
                title=data.get("title", ""),
                description=data.get("description", ""),
                priority=data.get("priority", "normal"),
                due_date=due,
                status=data.get("status", "todo"),
            )
            json_response(self, 201, todo)
        except ValueError as exc:
            json_response(self, 400, {"error": str(exc)})
        except Exception as exc:
            json_response(self, 500, {"error": str(exc)})

    def do_PUT(self) -> None:
        path = urlparse(self.path).path
        try:
            if not path.startswith("/api/todos/"):
                json_response(self, 404, {"error": "not found"})
                return
            todo_id = int(path.rsplit("/", 1)[-1])
            data = read_json(self)
            if "due_date" in data:
                data["due_date"] = validate_due_date(data.get("due_date"))
            todo = db.update_todo(todo_id, **data)
            if not todo:
                json_response(self, 404, {"error": "not found"})
            else:
                json_response(self, 200, todo)
        except ValueError as exc:
            json_response(self, 400, {"error": str(exc)})
        except Exception as exc:
            json_response(self, 500, {"error": str(exc)})

    def do_PATCH(self) -> None:
        path = urlparse(self.path).path
        try:
            if not path.endswith("/move") or not path.startswith("/api/todos/"):
                json_response(self, 404, {"error": "not found"})
                return
            parts = path.strip("/").split("/")
            todo_id = int(parts[2])
            data = read_json(self)
            status = data.get("status")
            if not status:
                raise ValueError("status is required")
            sort_order = data.get("sort_order")
            todo = db.move_todo(todo_id, status=status, sort_order=sort_order)
            if not todo:
                json_response(self, 404, {"error": "not found"})
            else:
                json_response(self, 200, todo)
        except ValueError as exc:
            json_response(self, 400, {"error": str(exc)})
        except Exception as exc:
            json_response(self, 500, {"error": str(exc)})

    def do_DELETE(self) -> None:
        path = urlparse(self.path).path
        try:
            if not path.startswith("/api/todos/"):
                json_response(self, 404, {"error": "not found"})
                return
            todo_id = int(path.rsplit("/", 1)[-1])
            if db.delete_todo(todo_id):
                json_response(self, 200, {"ok": True})
            else:
                json_response(self, 404, {"error": "not found"})
        except Exception as exc:
            json_response(self, 500, {"error": str(exc)})


def setup_logging() -> None:
    logging.basicConfig(
        filename=LOG_PATH,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        encoding="utf-8",
    )
    crash_log = LOG_PATH.open("a", encoding="utf-8")
    faulthandler.enable(file=crash_log, all_threads=True)


def shutdown_handler(signum: int, _frame) -> None:
    logging.info("signal %s received, shutting down", signum)
    print("\nShutting down gracefully…", flush=True)
    if SERVER is not None:
        SERVER.shutdown()


def main() -> None:
    global SERVER
    parser = argparse.ArgumentParser(description="Daily Doer local web app")
    parser.add_argument("--port", type=int, default=8780)
    parser.add_argument(
        "--single-thread",
        action="store_true",
        help="Handle one request at a time (not recommended on Windows)",
    )
    args = parser.parse_args()

    setup_logging()
    logging.info(
        "starting Daily Doer on port %s (single_thread=%s)",
        args.port,
        args.single_thread,
    )

    db.init_db()
    server_class = HTTPServer if args.single_thread else ThreadingHTTPServer
    SERVER = server_class(("127.0.0.1", args.port), Handler)
    SERVER.allow_reuse_address = True
    if hasattr(SERVER, "daemon_threads"):
        SERVER.daemon_threads = True

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(getattr(signal, "SIGTERM", signal.SIGINT), shutdown_handler)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, shutdown_handler)

    print(f"Daily Doer running at http://127.0.0.1:{args.port}", flush=True)
    print(f"Log file: {LOG_PATH}", flush=True)
    print("Press Ctrl+C to stop.", flush=True)
    try:
        SERVER.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        logging.info("keyboard interrupt")
        print("\nStopped.", flush=True)
    finally:
        SERVER.server_close()
        logging.info("server stopped")
        SERVER = None


if __name__ == "__main__":
    main()
