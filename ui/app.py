import sys
from pathlib import Path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import csv
import json
import os
import queue
import re
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
import urllib.request
import urllib.error
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath

try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox, simpledialog
except ImportError:
    tk = ttk = filedialog = messagebox = simpledialog = None

from core import *
from core import (_bech32_polymod, _bech32_hrp_expand, _convertbits,
                  _tls_context, _GO_SERVER_RE)

class App:
    def __init__(self, root):
        self.root = root
        root.title(APP_NAME)
        root.geometry("980x640")
        root.minsize(820, 520)
        root.configure(bg=BG)
        self.events = queue.Queue()
        self.accounts = []
        self.results = {}
        self.proc = None
        self.scan_thread = None
        self.transfer_thread = None
        self.server_lines = load_server_lines()
        self.server_state = {}
        self._srv_busy = False
        self._srv_after = None
        self._last_ok = -1
        self._closing = False
        self._build()
        self._fill_servers()
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        root.after(100, self._poll)
        root.after(800, self.check_servers)      # comprobación automática al abrir
        if self.engine_var.get():
            self._log(f"recovery-tool detectado: {Path(self.engine_var.get()).name}")
        else:
            self._log("recovery-tool no encontrado: colócalo en bin/recovery-tool.exe o pulsa BUSCAR…")

    # ---------------- UI
    def _btn(self, parent, text, cmd, bg=PANEL_ALT, fg=WHITE, **kw):
        return tk.Button(parent, text=text, command=cmd, bg=bg, fg=fg, relief="flat",
                         activebackground="#344760", padx=8, pady=3,
                         font=("Segoe UI", 8, "bold"), **kw)

    def _card(self, parent, title, var, color):
        f = tk.Frame(parent, bg=PANEL, padx=8, pady=2)
        f.pack(side="left", padx=(0, 5))
        tk.Label(f, text=title, bg=PANEL, fg=MUTED, font=("Segoe UI", 7, "bold")).pack(anchor="w")
        tk.Label(f, textvariable=var, bg=PANEL, fg=color, font=("Segoe UI", 11, "bold")).pack(anchor="w")

    def _tree(self, parent, columns, headings):
        wrap = tk.Frame(parent, bg=PANEL, padx=6, pady=6)
        wrap.pack(fill="both", expand=True)
        tv = ttk.Treeview(wrap, columns=columns, show="headings", selectmode="browse", height=6)
        for c in columns:
            title, w = headings[c]
            tv.heading(c, text=title)
            tv.column(c, width=w, anchor="w")
        sb = ttk.Scrollbar(wrap, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=sb.set)
        tv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        return tv

    def _build(self):
        st = ttk.Style()
        st.theme_use("clam")
        st.configure("Treeview", background=PANEL, foreground=WHITE, fieldbackground=PANEL, rowheight=21, borderwidth=0)
        st.configure("Treeview.Heading", background=PANEL_ALT, foreground=ORANGE, font=("Segoe UI", 9, "bold"), relief="flat")
        st.map("Treeview", background=[("selected", "#39516e")])
        st.configure("TNotebook", background=BG, borderwidth=0)
        st.configure("TNotebook.Tab", background=PANEL_ALT, foreground=WHITE, padding=(10, 3), font=("Segoe UI", 8, "bold"))
        st.map("TNotebook.Tab", background=[("selected", ORANGE)], foreground=[("selected", "#17202c")])
        st.configure("Horizontal.TProgressbar", troughcolor=PANEL_ALT, background=ORANGE)

        outer = tk.Frame(self.root, bg=BG, padx=8, pady=6)
        outer.pack(fill="both", expand=True)
        tk.Label(outer, text="MUUN RECOVERY PRO", bg=BG, fg=WHITE, font=("Segoe UI", 14, "bold")).pack(fill="x")
        tk.Label(outer, text="VERSION 1.0", bg=BG, fg=ORANGE, font=("Segoe UI", 8, "bold")).pack(fill="x")
        tk.Label(outer, text="RECOVERY • ELECTRUM • BITCOIN", bg=BG, fg=MUTED,
                 font=("Segoe UI", 7, "bold")).pack(fill="x", pady=(0, 4))

        # Tarjetas y banner en UNA sola fila (compacto) para dejar espacio a la tabla de cuentas.
        feats = tk.Frame(outer, bg=BG)
        feats.pack(fill="x", pady=(0, 4))
        for i, (title, text) in enumerate(FEATURES):
            card = tk.Frame(feats, bg=PANEL, padx=6, pady=3)
            card.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 4, 0))
            feats.columnconfigure(i, weight=1, uniform="feat")
            tk.Label(card, text=title, bg=PANEL, fg=ORANGE, font=("Segoe UI", 8, "bold"), anchor="w").pack(fill="x")
            tk.Label(card, text=text, bg=PANEL, fg=MUTED, font=("Segoe UI", 7), anchor="w",
                     justify="left", wraplength=150).pack(fill="x")
        banner = tk.Frame(feats, bg=PANEL_ALT, padx=6, pady=3)
        banner.grid(row=0, column=len(FEATURES), sticky="nsew", padx=(4, 0))
        feats.columnconfigure(len(FEATURES), weight=2, uniform="feat")
        tk.Label(banner, text=BANNER_TITLE, bg=PANEL_ALT, fg=GREEN, font=("Segoe UI", 8, "bold"),
                 anchor="w").pack(fill="x")
        tk.Label(banner, text=BANNER_TEXT, bg=PANEL_ALT, fg=WHITE, font=("Segoe UI", 7), anchor="w",
                 justify="left", wraplength=260).pack(fill="x")

        cards = tk.Frame(outer, bg=BG)
        cards.pack(fill="x", pady=(0, 4))
        self.v_accounts = tk.StringVar(value="0")
        self.v_utxos = tk.StringVar(value="0")
        self.v_funds = tk.StringVar(value="0.00000000 BTC")
        self.last_utxos_details = []
        self.v_counter = tk.StringVar(value="0 / 10.000")
        self.v_height = tk.StringVar(value="—")
        self.v_servers = tk.StringVar(value="0 / 0")
        self._card(cards, "CUENTAS", self.v_accounts, ORANGE)
        self._card(cards, "UTXOs", self.v_utxos, ORANGE)
        self._card(cards, "FONDOS", self.v_funds, GREEN)
        self._card(cards, "CONTADOR", self.v_counter, WHITE)
        self._card(cards, "BLOQUE (máx.)", self.v_height, WHITE)
        self._card(cards, "SERVIDORES OK", self.v_servers, GREEN)

        nb = ttk.Notebook(outer)
        nb.pack(fill="both", expand=True, pady=(0, 6))
        self._tab_accounts(nb)
        self._tab_servers(nb)
        self._tab_transaction(nb)

        tk.Label(outer, text="REGISTRO DE ACTIVIDAD", bg=BG, fg=ORANGE, font=("Segoe UI", 8, "bold")).pack(anchor="w")
        lf = tk.Frame(outer, bg=PANEL, padx=4, pady=4)
        lf.pack(fill="x")
        self.log = tk.Text(lf, height=4, bg="#111c2b", fg=MUTED, relief="flat",
                           font=("Consolas", 9), state="disabled", wrap="word")
        sb = ttk.Scrollbar(lf, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        self.log.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

    def _tab_accounts(self, nb):
        tab = tk.Frame(nb, bg=BG, padx=4, pady=8)
        nb.add(tab, text="  CUENTAS Y RESULTADOS  ")

        r1 = tk.Frame(tab, bg=BG)
        r1.pack(fill="x", pady=(0, 6))
        self._btn(r1, "ABRIR muun.zip", self.pick_zip, bg=ORANGE, fg="#17202c").pack(side="left")
        self._btn(r1, "ABRIR CARPETA", self.pick_folder).pack(side="left", padx=6)
        tk.Label(r1, text="Máx. entradas:", bg=BG, fg=MUTED).pack(side="left", padx=(12, 4))
        self.limit_var = tk.IntVar(value=MAX_ENTRIES)
        tk.Spinbox(r1, from_=1, to=MAX_ENTRIES, textvariable=self.limit_var, width=7).pack(side="left")
        self.src_var = tk.StringVar(value="Ningún origen seleccionado")
        tk.Label(r1, textvariable=self.src_var, bg=BG, fg=MUTED, anchor="w").pack(side="left", padx=10)

        r2 = tk.Frame(tab, bg=PANEL, padx=10, pady=8)
        r2.pack(fill="x", pady=(0, 6))
        tk.Label(r2, text="recovery-tool:", bg=PANEL, fg=WHITE).grid(row=0, column=0, sticky="w")
        self.engine_var = tk.StringVar(value=self._guess_engine())
        tk.Entry(r2, textvariable=self.engine_var, width=60).grid(row=0, column=1, padx=6, sticky="we")
        self._btn(r2, "BUSCAR…", self.pick_engine).grid(row=0, column=2)
        tk.Label(r2, text="Argumentos:", bg=PANEL, fg=WHITE).grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.args_var = tk.StringVar(value="-only-scan -generate-contacts")
        tk.Entry(r2, textvariable=self.args_var, width=60, state="readonly").grid(row=1, column=1, padx=6, pady=(6, 0), sticky="we")
        self.contacts_var = tk.BooleanVar(value=True)
        tk.Checkbutton(r2, text="Escaneo profundo: incluir direcciones de contactos (-generate-contacts)",
                       variable=self.contacts_var, bg=PANEL, fg=WHITE, selectcolor=PANEL_ALT, activebackground=PANEL,
                       activeforeground=WHITE, command=self._refresh_args).grid(row=2, column=1, padx=6, pady=(4, 0), sticky="w")
        tk.Label(r2, text="Servidor Electrum (opcional):", bg=PANEL, fg=WHITE).grid(row=3, column=0, sticky="w", pady=(4, 0))
        self.electrum_var = tk.StringVar(value="")
        e = tk.Entry(r2, textvariable=self.electrum_var, width=60)
        e.grid(row=3, column=1, padx=6, pady=(4, 0), sticky="we")
        e.bind("<KeyRelease>", lambda _e: self._refresh_args())
        r2.columnconfigure(1, weight=1)

        r3 = tk.Frame(tab, bg=BG)
        r3.pack(fill="x", pady=(0, 6))
        self.own_var = tk.BooleanVar(value=False)
        tk.Checkbutton(r3, text="Confirmo que la cuenta seleccionada es MI billetera",
                       variable=self.own_var, bg=BG, fg=WHITE, selectcolor=PANEL_ALT,
                       activebackground=BG, activeforeground=WHITE).pack(side="left")
        self.scan_btn = self._btn(r3, "ESCANEAR CUENTA SELECCIONADA", self.start_scan, bg=GREEN, fg="#102018")
        self.scan_btn.pack(side="left", padx=10)
        self.stop_btn = self._btn(r3, "DETENER", self.stop_scan, state="disabled")
        self.stop_btn.pack(side="left")
        self._btn(r3, "EXPORTAR CSV", self.export_csv).pack(side="left", padx=6)
        self._btn(r3, "ESCANEAR DIRECCIONES BTC", self.scan_addresses_dialog).pack(side="left", padx=6)
        self._btn(r3, "ESCANEAR LIGHTNING", self.scan_lightning_dialog).pack(side="left", padx=6)
        self._btn(r3, "ESCANEAR TODAS LAS CUENTAS", self.start_scan_all).pack(side="left", padx=6)
        self.status_var = tk.StringVar(value="Preparado.")
        tk.Label(r3, textvariable=self.status_var, bg=BG, fg=MUTED).pack(side="left", padx=8)

        r4 = tk.Frame(tab, bg=PANEL, padx=10, pady=8)
        r4.pack(fill="x", pady=(0, 6))
        tk.Label(r4, text="Destino para recuperar fondos:", bg=PANEL, fg=WHITE).pack(side="left")
        self.destination_var = tk.StringVar(value="")
        tk.Entry(r4, textvariable=self.destination_var, width=58).pack(side="left", padx=8, fill="x", expand=True)
        self._btn(r4, "COPIAR", self.copy_destination).pack(side="left", padx=(0, 8))
        self.transfer_btn = self._btn(r4, "TRANSFERIR CON recovery-tool", self.start_official_transfer,
                                      bg=ORANGE, fg="#17202c")
        self.transfer_btn.pack(side="left")
        tk.Label(tab, text="El barrido se hace en la consola del recovery-tool (sweeper.go): allí revisas importe y comisión y confirmas manualmente.",
                 bg=BG, fg=MUTED, font=("Segoe UI", 8)).pack(anchor="w", pady=(0, 5))

        self.progress = ttk.Progressbar(tab, mode="indeterminate", style="Horizontal.TProgressbar")
        self.progress.pack(fill="x", pady=(0, 6))

        cols = ("folder", "pdf", "code", "utxos", "funds", "status")
        heads = {"folder": ("Carpeta / cuenta", 250), "pdf": ("Emergency Kit", 200),
                 "code": ("Recovery Code", 250), "utxos": ("UTXOs", 70),
                 "funds": ("Fondos", 150), "status": ("Estado", 190)}
        self.table = self._tree(tab, cols, heads)
        self.table.tag_configure("funds", foreground=GREEN)
        self.table.tag_configure("warn", foreground=ORANGE)
        self.table.tag_configure("bad", foreground=RED)

        utxo_panel = tk.Frame(tab, bg=PANEL_ALT, padx=10, pady=8)
        utxo_panel.pack(fill="x", pady=(8, 0))
        tk.Label(utxo_panel, text="UTXOs DETECTADOS EN ESTE KIT (sats por UTXO)",
                 bg=PANEL_ALT, fg=MUTED, font=("Segoe UI", 8, "bold")).pack(anchor="w")
        self.accounts_utxos_var = tk.StringVar(
            value="Aún no se ha escaneado ningún kit. Aquí aparecerán los UTXOs con sus sats.")
        tk.Label(utxo_panel, textvariable=self.accounts_utxos_var, bg=PANEL_ALT, fg=ORANGE,
                 font=("Consolas", 9), justify="left", wraplength=850,
                 anchor="w").pack(anchor="w", pady=(4, 0))

    def _tab_servers(self, nb):
        tab = tk.Frame(nb, bg=BG, padx=4, pady=8)
        nb.add(tab, text="  SERVIDORES ELECTRUM  ")
        bar = tk.Frame(tab, bg=BG)
        bar.pack(fill="x", pady=(0, 6))
        self._btn(bar, "COMPROBAR SERVIDORES", self.check_servers, bg=ORANGE, fg="#17202c").pack(side="left")
        self._btn(bar, "EDITAR LISTA", self.edit_servers).pack(side="left", padx=6)
        self._btn(bar, "IMPORTAR servers.go", self.import_servers_go).pack(side="left")
        cols = ("server", "status", "latency", "height", "version", "error")
        heads = {"server": ("Servidor", 250), "status": ("Estado", 90), "latency": ("Latencia", 90),
                 "height": ("Bloque", 100), "version": ("Versión", 190), "error": ("Detalle", 340)}
        self.srv_table = self._tree(tab, cols, heads)
        self.srv_table.tag_configure("ok", foreground=GREEN)
        self.srv_table.tag_configure("bad", foreground=RED)

    def _tab_transaction(self, nb):
        """Transferencia independiente del escaneo; requiere autorización explícita."""
        tab = tk.Frame(nb, bg=BG)
        nb.add(tab, text="  TRANSFERENCIAS  ")

        canvas = tk.Canvas(tab, bg=BG, highlightthickness=0)
        scroll = ttk.Scrollbar(tab, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=BG, padx=18, pady=14)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        holder = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(holder, width=e.width))
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        def _on_wheel(e):
            try:
                canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
            except Exception:
                pass

        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _on_wheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        tk.Label(inner, text="TRANSFERIR SALDO RECUPERADO", bg=BG, fg=ORANGE,
                 font=("Segoe UI", 15, "bold")).pack(anchor="w", pady=(4, 8))
        tk.Label(
            inner,
            text=("RETIRO ON-CHAIN: los fondos detectados del kit se barren a una dirección "
                  "Bitcoin mainnet que tú pegues (bc1q…/bc1p…). El barrido lo ejecuta el motor "
                  "oficial de Muun en su propia consola: allí pedirá el Recovery Code, el destino "
                  "y la comisión, y confirmarás tú. La comisión on-chain se descuenta del monto "
                  "barrido y es ineludible. Esta interfaz no solicita ni almacena claves privadas."),
            bg=BG, fg=MUTED, justify="left", wraplength=760
        ).pack(anchor="w", pady=(0, 14))

        panel = tk.Frame(inner, bg=PANEL, padx=16, pady=14)
        panel.pack(fill="x", anchor="nw")

        tk.Label(panel, text="RETIRO ON-CHAIN (BTC)", bg=PANEL, fg=WHITE,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w")

        self.transfer_destination_label = tk.Label(panel, text="Dirección Bitcoin on-chain de destino (bc1…)",
                                                     bg=PANEL, fg=WHITE)
        self.transfer_destination_label.pack(anchor="w")
        self.transfer_destination_var = tk.StringVar()
        self.transfer_destination_entry = tk.Entry(
            panel, textvariable=self.transfer_destination_var, width=92,
            bg="#111c2b", fg=WHITE, insertbackground=WHITE, relief="flat"
        )
        self.transfer_destination_entry.pack(fill="x", pady=(5, 12), ipady=7)

        self.extract_btn = self._btn(
            panel, "EXTRAER UTXOs A ESTA DIRECCIÓN (BARRIDO ON-CHAIN)",
            self.execute_real_transfer, bg=GREEN, fg="#102018"
        )
        self.extract_btn.pack(anchor="w", pady=(0, 14))

        summary = tk.Frame(panel, bg=PANEL_ALT, padx=12, pady=10)
        summary.pack(fill="x", pady=(0, 12))
        tk.Label(summary, text="SALDO DETECTADO", bg=PANEL_ALT, fg=MUTED).grid(row=0, column=0, sticky="w")
        self.transfer_balance_var = tk.StringVar(value="0.00000000 BTC")
        tk.Label(summary, textvariable=self.transfer_balance_var, bg=PANEL_ALT, fg=GREEN,
                 font=("Segoe UI", 15, "bold")).grid(row=1, column=0, sticky="w", padx=(0, 35))
        tk.Label(summary, text="COMISIÓN", bg=PANEL_ALT, fg=MUTED).grid(row=0, column=1, sticky="w")
        self.transfer_fee_var = tk.StringVar(value="Se calculará en la wallet")
        tk.Label(summary, textvariable=self.transfer_fee_var, bg=PANEL_ALT, fg=WHITE,
                 font=("Segoe UI", 10, "bold")).grid(row=1, column=1, sticky="w", padx=(0, 35))
        tk.Label(summary, text="IMPORTE NETO", bg=PANEL_ALT, fg=MUTED).grid(row=0, column=2, sticky="w")
        self.transfer_net_var = tk.StringVar(value="Pendiente de cotización")
        tk.Label(summary, textvariable=self.transfer_net_var, bg=PANEL_ALT, fg=WHITE,
                 font=("Segoe UI", 10, "bold")).grid(row=1, column=2, sticky="w")
        summary.columnconfigure(2, weight=1)

        utxo_panel = tk.Frame(panel, bg=PANEL_ALT, padx=12, pady=8)
        utxo_panel.pack(fill="x", pady=(0, 12))
        tk.Label(utxo_panel, text="UTXOs DETECTADOS POR EL ESCANEO (con sats y dirección)",
                 bg=PANEL_ALT, fg=MUTED).pack(anchor="w")
        self.transfer_utxos_var = tk.StringVar(
            value="Aún no se ha escaneado ningún kit. Escanea una cuenta y aquí verás cada UTXO con sus sats."
        )
        tk.Label(utxo_panel, textvariable=self.transfer_utxos_var, bg=PANEL_ALT, fg=ORANGE,
                 font=("Consolas", 9), justify="left", wraplength=820,
                 anchor="w").pack(anchor="w", pady=(4, 0))

        self.transfer_hint_var = tk.StringVar(
            value=("BTC on-chain: pega una dirección Bitcoin mainnet bc1q… o bc1p…. "
                   "El botón EXTRAER abre el recovery-tool, que barre TODOS los fondos "
                   "detectados del kit a esa dirección. La comisión on-chain se descuenta "
                   "del monto barrido (ineludible).")
        )
        tk.Label(panel, textvariable=self.transfer_hint_var, bg=PANEL, fg=MUTED,
                 justify="left", wraplength=760).pack(anchor="w", pady=(0, 10))

        self.transfer_preview = tk.Text(
            inner, height=8, bg="#111c2b", fg=WHITE, relief="flat",
            font=("Consolas", 9), wrap="word", state="disabled"
        )
        self.transfer_preview.pack(fill="both", expand=True, pady=(12, 0))

        tk.Label(
            inner,
            text=("RECUPERACIÓN (escaneo) y TRANSFERENCIA son procesos independientes: escanear nunca envía fondos y enviar nunca escanea. "
                  "El barrido ON-CHAIN lo ejecuta el recovery-tool oficial en una consola propia e interactiva. "
                  "La dirección destino se copia automáticamente al portapapeles al pulsar EXTRAER. "
                  "Los pagos confirmados son irreversibles. "
                  "Nunca pegues Recovery Code, semilla ni claves privadas en esta ventana."),
            bg=BG, fg=ORANGE, justify="left", wraplength=760
        ).pack(anchor="w", pady=(10, 0))

    def preview_transfer(self):
        destination = self.transfer_destination_var.get().strip()
        if not destination:
            messagebox.showwarning(APP_NAME, "Introduce la dirección Bitcoin on-chain de destino.")
            return False
        try:
            address_to_scripthash(destination)
        except Exception:
            messagebox.showerror(
                APP_NAME,
                "La dirección no parece una dirección SegWit Bitcoin mainnet válida (bc1q/bc1p)."
            )
            return
        dest_label = "Dirección Bitcoin"
        masked = destination[:12] + "…" + destination[-8:]
        fee_text = "Comisión del barrido (la descuenta el motor Muun del monto barrido; ineludible)"
        net_text = "Saldo detectado menos comisión on-chain"
        route_text = "BTC on-chain"
        balance = self.v_funds.get() if hasattr(self, "v_funds") else "No disponible"
        utxo_detail = utxo_summary_text(self.last_utxos_details)
        report = (
            "RESUMEN PREVIO — NO SE HA ENVIADO NINGÚN FONDO\n"
            "================================================\n"
            f"Red: {route_text}\n"
            f"{dest_label}: {masked}\n"
            f"Saldo detectado por el escaneo: {balance}\n"
            f"UTXOs detectados:\n{utxo_detail}\n"
            f"Comisión: {fee_text}\n"
            f"Importe neto: {net_text}\n\n"
            "Estado: destino validado preliminarmente. Falta cotizar la comisión y "
            "confirmar el importe exacto en una wallet compatible.\n"
            "El envío real requiere autorización explícita (casilla de propiedad + frase)."
        )
        self.transfer_balance_var.set(balance)
        self.transfer_fee_var.set(fee_text)
        self.transfer_net_var.set(net_text)
        self.transfer_preview.configure(state="normal")
        self.transfer_preview.delete("1.0", "end")
        self.transfer_preview.insert("end", report)
        self.transfer_preview.configure(state="disabled")
        self._log("Destino BTC on-chain validado preliminarmente; no se realizó transferencia.")
        return True


    def execute_real_transfer(self):
        """Extrae los UTXOs detectados del kit a una dirección on-chain (barrido).

        Valida la dirección, exige autorización explícita y abre el recovery-tool oficial
        en una consola propia e INTERACTIVA: allí el usuario pega el destino (ya copiado al
        portapapeles) e introduce el Recovery Code, la comisión y confirma el barrido.
        Este programa no firma nada por su cuenta ni declara los fondos de terceros como suyos.
        """
        destination = self.transfer_destination_var.get().strip()
        if not destination:
            messagebox.showwarning(APP_NAME, "Pega la dirección Bitcoin on-chain de destino (bc1…).")
            return
        try:
            address_to_scripthash(destination)
        except Exception:
            messagebox.showerror(
                APP_NAME,
                "Dirección Bitcoin mainnet inválida para barrido SegWit (bc1q/bc1p)."
            )
            return
        self.preview_transfer()
        confirmation = (
            "VAS A ABRIR EL recovery-tool PARA BARRER TODOS LOS FONDOS DETECTADOS DEL KIT.\n\n"
            f"Dirección destino: {destination}\n"
            f"Fondos detectados por el escaneo: {self.v_funds.get()}\n\n"
            "La comisión on-chain se descuenta del monto barrido y es ineludible. "
            "Los envíos son irreversibles.\n\n"
            "Se abrirá una consola interactiva: pega allí el destino (ya está copiado "
            "al portapapeles), introduce el Recovery Code y confirma el barrido."
        )
        if not self._authorize_send(confirmation):
            return
        self._copy_to_clipboard(destination)
        self.start_official_transfer(pre_authorized=True, destination=destination)

    # ---------------- utilidades
    def _log(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", time.strftime("%H:%M:%S ") + text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _guess_engine(self):
        """Busca el recovery-tool junto al programa (incluida bin/), en recovery_tool/ y en el PATH."""
        here = Path(__file__).resolve().parent.parent
        names = ("recovery-tool.exe", "recovery-tool", "rt-new", "recovery_tool.exe")
        for name in names:
            for base in (here, here / "bin", here / "recovery_tool", here / "recovery_tool" / "bin"):
                candidate = base / name
                if candidate.is_file():
                    return str(candidate)
        for name in ("recovery-tool.exe", "recovery-tool"):
            found = shutil.which(name)
            if found:
                return found
        return ""

    # ---------------- cuentas
    def pick_zip(self):
        p = filedialog.askopenfilename(title="Selecciona muun.zip", filetypes=[("ZIP", "*.zip"), ("Todos", "*.*")])
        if p:
            self.load_source("zip", p)

    def pick_folder(self):
        p = filedialog.askdirectory(title="Selecciona la carpeta con las cuentas")
        if p:
            self.load_source("dir", p)

    def pick_engine(self):
        p = filedialog.askopenfilename(title="Selecciona recovery-tool")
        if p:
            self.engine_var.set(p)

    def load_source(self, kind, path):
        try:
            limit = int(self.limit_var.get())
        except (tk.TclError, ValueError):
            limit = MAX_ENTRIES
        limit = max(1, min(MAX_ENTRIES, limit))
        try:
            accts = discover_zip(path, limit) if kind == "zip" else discover_folder(path, limit)
        except (OSError, zipfile.BadZipFile) as exc:
            messagebox.showerror(APP_NAME, f"No se pudo leer el origen:\n{exc}")
            return
        self.accounts = accts
        self.results = {}
        self.src_var.set(path)
        self.table.delete(*self.table.get_children())
        for i, a in enumerate(accts):
            if a["code"]:
                status = "Listo para escanear"
            elif a.get("code_error"):
                status = a["code_error"]
            elif a["pdf"]:
                status = "Falta código"
            else:
                status = "Faltan PDF o código"
            ok = bool(a["pdf"] and a["code"])
            self.table.insert("", "end", iid=str(i), tags=("" if ok else "warn",), values=(
                a["folder"], a["pdf_name"] or "— sin PDF —", mask(a["code"]) if a["code"] else "— sin código —",
                "", "", status))
        self.v_accounts.set(str(len(accts)))
        self.v_counter.set(f"{len(accts):,} / {limit:,}".replace(",", "."))
        self._recalc_totals()
        self._log(f"Origen cargado: {len(accts)} cuenta(s) detectada(s).")

    # ---------------- escaneo
    def _refresh_args(self):
        try:
            self.args_var.set(" ".join(build_scan_flags(self.electrum_var.get(), self.contacts_var.get())))
        except ValueError:
            self.args_var.set("(servidor Electrum inválido)")

    def start_scan(self):
        sel = self.table.selection()
        if not sel:
            messagebox.showinfo(APP_NAME, "Selecciona una cuenta en la tabla.")
            return
        if not self.own_var.get():
            messagebox.showwarning(APP_NAME, "Marca la casilla de confirmación: solo se escanea tu propia billetera.")
            return
        idx = int(sel[0])
        acct = self.accounts[idx]
        try:
            flags = build_scan_flags(self.electrum_var.get(), self.contacts_var.get())
        except ValueError as exc:
            messagebox.showwarning(APP_NAME, str(exc))
            return
        if not acct["pdf"] or not acct["code"]:
            messagebox.showwarning(APP_NAME, "Esa cuenta no tiene PDF o Recovery Code.")
            return
        engine = self.engine_var.get().strip().strip('"')
        if not engine or not os.path.isfile(engine):
            messagebox.showwarning(APP_NAME, "Indica la ruta del recovery-tool.")
            return
        if self.scan_thread and self.scan_thread.is_alive():
            return
        self.scan_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.progress.start(12)
        self.status_var.set(f"Escaneando {acct['folder']}…")
        self.scan_thread = threading.Thread(target=self._scan_worker, args=(idx, acct, engine, flags), daemon=True)
        self.scan_thread.start()

    def _scan_worker(self, idx, acct, engine, extra_args):
        tmp = tempfile.mkdtemp(prefix="muun_")
        lines = []
        status = "Terminado"
        stage = "copiar el PDF temporal"
        proc = None
        try:
            pdf = materialize_pdf(acct, tmp)
            stage = "ejecutar el recovery-tool"
            cmd = [engine, *extra_args, str(pdf)]
            self.events.put(("log", f"Ejecutando: {Path(engine).name} {' '.join(extra_args)} EmergencyKit.pdf"))
            proc = subprocess.Popen(cmd, cwd=tmp, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                    errors="replace", bufsize=1)
            self.proc = proc
            try:
                proc.stdin.write(acct["code"] + "\n")
                proc.stdin.flush()
                proc.stdin.close()
            except OSError:
                pass

            # La lectura va en un hilo aparte para poder vigilar el tiempo y responder a DETENER
            # aunque el motor no escriba nada (por ejemplo si se queda esperando entrada).
            salida = queue.Queue()

            def leer():
                try:
                    for raw in proc.stdout:
                        salida.put(raw)
                finally:
                    salida.put(None)

            threading.Thread(target=leer, daemon=True).start()

            inicio = time.monotonic()
            while True:
                restante = SCAN_TIMEOUT - (time.monotonic() - inicio)
                if restante <= 0:
                    status = "Tiempo agotado"
                    break
                try:
                    raw = salida.get(timeout=min(1.0, restante))
                except queue.Empty:
                    if proc.poll() is not None:
                        break
                    continue
                if raw is None:
                    break
                line = raw.rstrip()
                if acct["code"] in line:
                    line = line.replace(acct["code"], mask(acct["code"]))
                lines.append(line)
                if line.strip():
                    self.events.put(("log", line[:200]))
                if "Couldn't read the PDF" in line:
                    status = "PDF ilegible"
                    self.events.put(("log", "El Emergency Kit no se pudo leer: usa el PDF original "
                                            "exportado por Muun (no una captura ni un PDF reconstruido)."))
                    break

            if status != "Terminado" and proc.poll() is None:
                try:
                    proc.kill()
                except OSError:
                    pass
            try:
                code = proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                code = -1
            if status == "Terminado" and code != 0:
                status = f"Salió con código {code}"
        except OSError as exc:
            code = getattr(exc, "winerror", None) or exc.errno
            hints = {
                193: "el .exe no es válido en este Windows (descarga incompleta o arquitectura incorrecta)",
                5: "acceso denegado (antivirus/Defender o permisos): permite el .exe o ejecútalo como administrador",
                740: "el .exe requiere ejecutarse como administrador",
                2: "no se encuentra el archivo (revisa la ruta del recovery-tool)",
                3: "ruta no encontrada",
                87: "argumento no válido",
            }
            status = f"OSError {code}"
            self.events.put(("log", f"OSError [{code}] en «{stage}»: {exc.strerror or exc}"))
            self.events.put(("log", "Causa probable: " + hints.get(code, "ver el mensaje anterior")))
        except Exception as exc:  # noqa: BLE001
            status = f"Error: {type(exc).__name__}"[:40]
            self.events.put(("log", f"Error en «{stage}»: {exc}"))
        finally:
            # Conserva el error_log que el motor escribe en el directorio temporal.
            try:
                elog = Path(tmp) / "error_log"
                if elog.is_file():
                    logs = Path(__file__).parent / "logs"
                    logs.mkdir(exist_ok=True)
                    stamp = time.strftime("%Y%m%d_%H%M%S")
                    dest = logs / ("error_log_" + stamp + ".txt")
                    shutil.copyfile(elog, dest)
                    self.events.put(("log", "Diagnóstico del motor guardado en logs/" + dest.name))
            except OSError:
                pass
            if proc is not None and proc.poll() is None:
                try:
                    proc.kill()
                except OSError:
                    pass
            shutil.rmtree(tmp, ignore_errors=True)
            self.proc = None
        utxos, sats = parse_scan_output(lines)
        details = parse_scan_utxos(lines)
        self.events.put(("scan_done", idx, utxos, sats, status, details))


    def scan_addresses_dialog(self):
        win = tk.Toplevel(self.root)
        win.title("Escaneo directo de direcciones Bitcoin")
        win.configure(bg=BG)
        win.geometry("760x520")
        tk.Label(win, text="Pega una dirección Bitcoin por línea (bc1q o bc1p).", bg=BG, fg=WHITE,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=12, pady=(12, 5))
        box = tk.Text(win, height=9, bg=PANEL, fg=WHITE, insertbackground=WHITE, font=("Consolas", 10))
        box.pack(fill="x", padx=12)
        opt = tk.Frame(win, bg=BG)
        opt.pack(fill="x", padx=12, pady=6)
        tk.Label(opt, text="Desde el bloque:", bg=BG, fg=WHITE).pack(side="left")
        from_var = tk.StringVar(value="0")
        tk.Entry(opt, textvariable=from_var, width=10, bg=PANEL, fg=WHITE, insertbackground=WHITE).pack(side="left", padx=6)
        tk.Label(opt, text="Consulta real y de solo lectura (sin Recovery Code ni claves).",
                 bg=BG, fg=MUTED).pack(side="left", padx=8)
        output = tk.Text(win, bg="#111c2b", fg=WHITE, state="disabled", wrap="word", height=12)
        output.pack(fill="both", expand=True, padx=12, pady=6)
        def append(msg):
            output.configure(state="normal")
            output.insert("end", msg + "\n")
            output.see("end")
            output.configure(state="disabled")
        def start():
            addresses = list(dict.fromkeys(x.strip() for x in box.get("1.0", "end").splitlines() if x.strip()))
            if not addresses:
                messagebox.showinfo(APP_NAME, "Pega al menos una dirección.", parent=win)
                return
            try:
                from_height = max(0, int(from_var.get().strip() or "0"))
            except ValueError:
                messagebox.showinfo(APP_NAME, "«Desde el bloque» debe ser un número.", parent=win)
                return
            btn.configure(state="disabled")
            append("Iniciando consulta Electrum...")
            threading.Thread(target=worker, args=(addresses, from_height), daemon=True).start()
        def worker(addresses, from_height=0):
            total_sats = 0
            total_utxos = 0
            total_confirmed = 0
            total_unconfirmed = 0
            seen_outpoints = set()
            servers = rank_servers(self.server_lines[:MAX_SERVERS], self.server_state)
            for address in addresses:
                try:
                    sh = address_to_scripthash(address)
                except ValueError as exc:
                    self.root.after(0, lambda a=address, e=exc: append(f"{a}: DIRECCIÓN INVÁLIDA — {e}"))
                    continue
                payload = None
                last_error = "No hay servidores Electrum configurados."
                for host, port, use_ssl in servers:
                    try:
                        version, history, unspent, balance = electrum_address_data(host, port, use_ssl, sh)
                        payload = (host, version, history, unspent, balance)
                        break
                    except Exception as exc:
                        last_error = f"{host}: {type(exc).__name__}: {exc}"
                if payload is None:
                    self.root.after(0, lambda a=address, e=last_error: append(f"{a}: ERROR Electrum — {e}"))
                    continue
                host, version, history, unspent, balance = payload
                # Importes históricos recibidos por la dirección (incluso salidas ya gastadas).
                tx_output_values = {}
                for h in (history or []):
                    htxid = str(h.get("tx_hash", "")).lower()
                    try:
                        tx = electrum_tx_verbose(host, port, use_ssl, htxid)
                        vals = []
                        for vout in (tx.get("vout") or []):
                            spk = vout.get("scriptPubKey") or {}
                            out_addr = spk.get("address")
                            if out_addr and str(out_addr).lower() == address.lower():
                                val = vout.get("value", 0)
                                try:
                                    sats_val = int(round(float(val) * 100_000_000))
                                except (TypeError, ValueError):
                                    sats_val = 0
                                vals.append((int(vout.get("n", 0)), sats_val))
                        tx_output_values[htxid] = vals
                    except Exception:  # noqa: BLE001
                        tx_output_values[htxid] = []
                normalized = []
                for item in unspent:
                    txid = str(item.get("tx_hash", "")).lower()
                    vout = int(item.get("tx_pos", 0))
                    key = (txid, vout)
                    if not re.fullmatch(r"[0-9a-f]{64}", txid) or key in seen_outpoints:
                        continue
                    seen_outpoints.add(key)
                    height = int(item.get("height", 0) or 0)
                    normalized.append({
                        "tx_hash": txid, "tx_pos": vout,
                        "value": int(item.get("value", 0)),
                        "height": height, "confirmed": height > 0
                    })
                sats = sum(x["value"] for x in normalized)
                confirmed = sum(x["value"] for x in normalized if x["confirmed"])
                unconfirmed = sats - confirmed
                total_sats += sats
                total_utxos += len(normalized)
                total_confirmed += confirmed
                total_unconfirmed += unconfirmed
                lines = [
                    f"{address}",
                    f"  Servidor: {host} | versión: {version}",
                    f"  TX históricas: {len(history)}",
                    f"  UTXOs actuales: {len(normalized)}",
                    f"  Total no gastado: {sats:,} sats = {sats / 1e8:.8f} BTC",
                    f"  Confirmado: {confirmed:,} sats | pendiente: {unconfirmed:,} sats",
                ]
                lines.append(f"  Saldo Electrum: confirmado {int(balance.get('confirmed', 0)):,} sats | "
                             f"pendiente {int(balance.get('unconfirmed', 0)):,} sats")
                report = build_block_report(history, unspent, from_height, tx_output_values)
                if report:
                    lines.append("  BLOQUE A BLOQUE (entrada/salida real):")
                    for height, txs in report:
                        lines.append(f"    Bloque {height:,}" if height else "    Mempool (pendiente)")
                        for tx in txs:
                            if tx["utxos"]:
                                outs = ", ".join(f"{v:,} sats @vout {n}" for n, v in tx["utxos"])
                                lines.append(f"      ENTRADA  {tx['txid']}  UTXO: {outs}")
                            elif tx.get("funded"):
                                outs = ", ".join(f"{v:,} sats @vout {n}" for n, v in tx["funded"])
                                lines.append(f"      GASTADA  {tx['txid']}  (recibió {outs}; salida ya gastada)")
                            else:
                                lines.append(f"      GASTADA  {tx['txid']}  (entrada y salida ya ocurridas)")
                elif history:
                    lines.append(f"  Hay {len(history)} TX, ninguna desde el bloque {from_height:,}.")
                hist_rows = []
                for txid, outs in tx_output_values.items():
                    for vout, sats in outs:
                        state = "UTXO ACTUAL" if (txid, vout) in seen_outpoints else "GASTADA"
                        hist_rows.append((txid, vout, sats, state))
                if hist_rows:
                    lines.append("  Salidas financiadas a esta dirección (histórico, incluidas las ya gastadas):")
                    for txid, vout, sats, state in hist_rows:
                        lines.append(f"    {txid}:{vout} | {sats:,} sats | {state}")
                    hist_total = sum(x[2] for x in hist_rows)
                    lines.append(f"  Total histórico recibido: {hist_total:,} sats")
                if normalized:
                    lines.append("  UTXOs (TXID:VOUT | SATS | CONFIRMACIONES):")
                    for item in normalized:
                        state = "PENDIENTE" if not item["confirmed"] else f"altura {item['height']}"
                        lines.append(f"    {item['tx_hash']}:{item['tx_pos']} | {item['value']:,} | {state}")
                else:
                    lines.append("  Sin UTXOs no gastados para esta dirección.")
                self.root.after(0, lambda msg="\n".join(lines): append(msg))
            summary = (
                f"\nTOTAL SIN DUPLICADOS: {total_utxos} UTXO(s) | "
                f"{total_sats:,} sats = {total_sats / 1e8:.8f} BTC\n"
                f"CONFIRMADO: {total_confirmed:,} sats | PENDIENTE: {total_unconfirmed:,} sats\n"
                "El historial incluye TX confirmadas y no confirmadas; los UTXOs son solo salidas aún no gastadas."
            )
            self.root.after(0, lambda: append(summary))
            self.root.after(0, lambda: btn.configure(state="normal"))
        btn = self._btn(win, "CONSULTAR UTXOs", start, bg=GREEN, fg="#102018")
        btn.pack(pady=6)

    def scan_lightning_dialog(self):
        win = tk.Toplevel(self.root)
        win.title("Escaneo Lightning (LNbits)")
        win.configure(bg=BG)
        win.geometry("760x520")
        tk.Label(win, text="Historial Lightning: entradas y salidas (solo lectura, vía LNbits).",
                 bg=BG, fg=WHITE, font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=12, pady=(12, 5))
        tk.Label(win, text="Usa las variables de entorno MUUN_LNBITS_URL y MUUN_LNBITS_INVOICE_KEY.",
                 bg=BG, fg=MUTED).pack(anchor="w", padx=12)
        output = tk.Text(win, bg="#111c2b", fg=WHITE, state="disabled", wrap="word", height=18)
        output.pack(fill="both", expand=True, padx=12, pady=6)
        def append(msg):
            output.configure(state="normal")
            output.insert("end", msg + "\n")
            output.see("end")
            output.configure(state="disabled")
        def start():
            url = os.environ.get("MUUN_LNBITS_URL", "").strip()
            key = os.environ.get("MUUN_LNBITS_INVOICE_KEY", "").strip()
            if not url or not key:
                messagebox.showwarning(APP_NAME, "Configura MUUN_LNBITS_URL y MUUN_LNBITS_INVOICE_KEY.", parent=win)
                return
            btn.configure(state="disabled")
            append("Consultando LNbits...")
            threading.Thread(target=worker, daemon=True).start()
        def worker():
            inc, out, count, rows, err = scan_lightning_payments(url, key)
            if err:
                self.root.after(0, lambda: append(f"ERROR: {err}"))
                self.root.after(0, lambda: btn.configure(state="normal"))
                return
            for r in rows:
                self.root.after(0, lambda rr=r: append(f"  {rr['direction']:7} {rr['sats']:>10,} sats  {rr['status']}  {rr['memo']}"))
            summary = (f"\nTOTAL: {count} pagos | ENTRADAS: {inc:,} sats | SALIDAS: {out:,} sats | "
                       f"NETO: {inc - out:,} sats")
            self.root.after(0, lambda: append(summary))
            self.root.after(0, lambda: btn.configure(state="normal"))
        btn = self._btn(win, "CONSULTAR LIGHTNING", start, bg=GREEN, fg="#102018")
        btn.pack(pady=6)

    def start_scan_all(self):
        if not self.accounts:
            messagebox.showinfo(APP_NAME, "Carga primero un ZIP o una carpeta.")
            return
        if not self.own_var.get():
            messagebox.showwarning(APP_NAME, "Marca la casilla de confirmación: solo se escanea tu propia billetera.")
            return
        engine = self.engine_var.get().strip()
        if not engine:
            messagebox.showwarning(APP_NAME, "Indica la ruta del recovery-tool.")
            return
        if self.scan_thread and self.scan_thread.is_alive():
            messagebox.showwarning(APP_NAME, "Ya hay un escaneo en curso.")
            return
        self.scan_btn.configure(state="disabled")
        flags = build_scan_flags(self.electrum_var.get(), self.contacts_var.get())
        self.status_var.set("Escaneando todas las cuentas…")
        self._log(f"Iniciando escaneo de {len(self.accounts)} cuenta(s)…")
        self.scan_thread = threading.Thread(target=self._scan_all_worker, args=(engine, flags), daemon=True)
        self.scan_thread.start()

    def _scan_all_worker(self, engine, extra_args):
        for idx, acct in enumerate(list(self.accounts)):
            if self._closing:
                break
            try:
                self._scan_worker(idx, acct, engine, extra_args)
            except Exception as exc:  # noqa: BLE001
                self._log(f"Error en cuenta {acct.get('folder')}: {exc}")
        self.events.put(("scan_all_done", len(self.accounts)))
        self.root.after(0, lambda: self.scan_btn.configure(state="normal"))
        self.root.after(0, lambda: self.status_var.set("Escaneo completo."))

    def copy_destination(self):
        address = self.destination_var.get().strip()
        if not address:
            messagebox.showwarning(APP_NAME, "Introduce una dirección Bitcoin de destino.")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(address)
        self._log("Dirección de destino copiada al portapapeles.")

    def start_official_transfer(self, transfer_options=None, pre_authorized=False, destination=""):
        """Barrido con el recovery-tool (sweeper.go) en una consola propia e INTERACTIVA.

        Independiente del escaneo: exige casilla de propiedad + frase AUTORIZO ENVIAR, salvo
        que ya se haya autorizado desde el botón EXTRAER (pre_authorized=True). El
        Recovery Code, el destino y la comisión se escriben en la consola del recovery-tool,
        que pide su propia confirmación antes de firmar y transmitir. Este programa NO pasa el
        Recovery Code por stdin en este modo y no firma nada por su cuenta.
        """
        sel = self.table.selection()
        if not sel:
            messagebox.showinfo(APP_NAME, "Selecciona la cuenta a transferir en la tabla.")
            return
        acct = self.accounts[int(sel[0])]
        if not acct["pdf"]:
            messagebox.showwarning(APP_NAME, "Esa cuenta no tiene Emergency Kit (PDF).")
            return
        engine = self.engine_var.get().strip().strip('"')
        if not engine or not os.path.isfile(engine):
            messagebox.showwarning(APP_NAME, "Indica la ruta del recovery-tool.")
            return
        if os.name != "nt":
            messagebox.showinfo(APP_NAME, "En este sistema ejecuta manualmente:\n"
                                f"{engine} EmergencyKit.pdf\nen una terminal.")
            return
        if self.scan_thread and self.scan_thread.is_alive():
            messagebox.showwarning(APP_NAME, "Espera a que termine el escaneo en curso.")
            return
        resumen = (
            "VAS A ABRIR EL recovery-tool PARA BARRER FONDOS REALES.\n\n"
            f"Cuenta: {acct['folder']}\nFondos detectados: {self.v_funds.get()}\n"
            + (f"Destino on-chain: {destination}\n" if destination else "") +
            "\nEn la consola que se abrirá introducirás el Recovery Code, el destino y la comisión, "
            "y confirmarás allí. Los envíos son irreversibles."
        )
        if not (pre_authorized or self._authorize_send(resumen)):
            return
        try:
            tmp = tempfile.mkdtemp(prefix="muun_sweep_")
            pdf = materialize_pdf(acct, tmp)
            proc = subprocess.Popen([engine, str(pdf)], cwd=tmp,
                                    creationflags=subprocess.CREATE_NEW_CONSOLE)
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"No se pudo abrir el recovery-tool:\n{exc}")
            return
        self.transfer_btn.configure(state="disabled")
        self.extract_btn.configure(state="disabled")
        self.status_var.set("Transferencia en la consola del recovery-tool…")
        self._log(f"recovery-tool abierto para {acct['folder']}; completa y confirma en su consola.")
        if destination:
            self._log(f"Destino on-chain listo para pegar: {destination}")

        def waiter():
            code = proc.wait()
            shutil.rmtree(tmp, ignore_errors=True)
            self.events.put(("transfer_done", f"recovery-tool terminó (código {code})."))
        threading.Thread(target=waiter, daemon=True).start()

    def stop_scan(self):
        if self.proc:
            try:
                self.proc.kill()
            except OSError:
                pass
            self.status_var.set("Deteniendo…")
            self._log("Escaneo detenido por el usuario.")

    def _copy_to_clipboard(self, text):
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.root.update()
            self._log("Dirección copiada al portapapeles (pega con Ctrl+V en la consola del recovery-tool).")
        except Exception as exc:
            self._log(f"No se pudo copiar al portapapeles ({exc}); cópiala manualmente: {text}")

    def _update_transfer_utxos(self):
        try:
            if self.last_utxos_details:
                self.transfer_utxos_var.set(utxo_summary_text(self.last_utxos_details))
            else:
                self.transfer_utxos_var.set(
                    "Aún no se ha detectado ningún UTXO. Escanea una cuenta primero.")
        except Exception:
            pass

    def _recalc_totals(self):
        utxos = sum(r["utxos"] for r in self.results.values())
        sats = sum(r["sats"] or 0 for r in self.results.values())
        self.v_utxos.set(str(utxos))
        self.v_funds.set(fmt_btc(sats))
        if hasattr(self, "transfer_balance_var"):
            self.transfer_balance_var.set(fmt_btc(sats))
        details = []
        for r in self.results.values():
            details.extend(r.get("details") or [])
        self.last_utxos_details = details
        self._update_transfer_utxos()
        if hasattr(self, "accounts_utxos_var"):
            self.accounts_utxos_var.set(utxo_summary_text(details))

    # ---------------- servidores
    def _fill_servers(self):
        self.srv_table.delete(*self.srv_table.get_children())
        for i, line in enumerate(self.server_lines[:MAX_SERVERS]):
            self.srv_table.insert("", "end", iid=str(i), values=(line, "—", "", "", "", ""))
        self.v_servers.set(f"0 / {len(self.server_lines[:MAX_SERVERS])}")

    def check_servers(self):
        if self._srv_busy:
            return
        self._srv_busy = True
        if self._srv_after:
            try:
                self.root.after_cancel(self._srv_after)
            except ValueError:
                pass
            self._srv_after = None
        parsed = []
        for i, line in enumerate(self.server_lines[:MAX_SERVERS]):
            try:
                p = parse_server(line)
            except ValueError as exc:
                self.srv_table.item(str(i), values=(line, "INVÁLIDO", "", "", "", str(exc)), tags=("bad",))
                continue
            if p:
                parsed.append((i, p))

        def run():
            with ThreadPoolExecutor(max_workers=16) as pool:
                futs = [(i, pool.submit(check_server_retry, *p)) for i, p in parsed]
                for i, f in futs:
                    self.events.put(("server", i, f.result()))
            self.events.put(("servers_done",))

        threading.Thread(target=run, daemon=True).start()

    def import_servers_go(self):
        path = filedialog.askopenfilename(title="Selecciona servers.go", filetypes=[("Go", "*.go"), ("Todos", "*.*")])
        if not path:
            return
        try:
            lines = parse_servers_go(Path(path).read_text(encoding="utf-8", errors="replace"))
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"No se pudo leer el archivo:\n{exc}")
            return
        if not lines:
            messagebox.showwarning(APP_NAME, "No se encontró PublicServers en ese archivo.")
            return
        self.server_lines = lines
        try:
            save_server_lines(lines)
        except OSError as exc:
            messagebox.showwarning(APP_NAME, f"{exc}\nLa lista queda activa solo en esta sesión.")
        self.server_state = {}
        self._fill_servers()
        self._log(f"servers.go importado: {len(lines)} servidor(es) (máx. {MAX_SERVERS}).")
        self.check_servers()

    def _authorize_send(self, resumen):
        """Pide casilla de propiedad + escribir la frase exacta antes de firmar/enviar."""
        if not self.own_var.get():
            messagebox.showwarning(APP_NAME, "Marca la casilla de confirmación: solo envías fondos de tu propia billetera.")
            return False
        typed = simpledialog.askstring(
            APP_NAME, resumen + f"\n\nEscribe exactamente  {SEND_PHRASE}  para firmar y enviar:", parent=self.root)
        if not authorization_ok(typed, self.own_var.get()):
            self._log("Envío cancelado: autorización no confirmada.")
            return False
        return True

    def edit_servers(self):
        win = tk.Toplevel(self.root)
        win.title("Lista de servidores (host:puerto:s|t, máx. 300)")
        win.configure(bg=BG)
        txt = tk.Text(win, width=60, height=18, font=("Consolas", 10))
        txt.pack(padx=10, pady=10)
        txt.insert("1.0", "\n".join(self.server_lines))

        def save():
            lines = [l.strip() for l in txt.get("1.0", "end").splitlines() if l.strip()][:MAX_SERVERS]
            try:
                for l in lines:
                    parse_server(l)
            except ValueError as exc:
                messagebox.showerror(APP_NAME, str(exc), parent=win)
                return
            self.server_lines = lines
            try:
                save_server_lines(lines)
            except OSError as exc:
                messagebox.showwarning(APP_NAME, f"{exc}\nLa lista queda activa solo en esta sesión.",
                                       parent=win)
            self.server_state = {}
            self._fill_servers()
            win.destroy()

        self._btn(win, "GUARDAR", save, bg=GREEN, fg="#102018").pack(pady=(0, 10))

    # ---------------- exportar
    def export_csv(self):
        if not self.accounts:
            messagebox.showinfo(APP_NAME, "No hay datos que exportar.")
            return
        p = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not p:
            return
        with open(p, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(["carpeta", "pdf", "utxos", "sats", "btc", "estado"])
            for i, a in enumerate(self.accounts):
                r = self.results.get(i)
                w.writerow([a["folder"], a["pdf_name"], r["utxos"] if r else "",
                            r["sats"] if r and r["sats"] is not None else "",
                            f"{r['sats'] / 1e8:.8f}" if r and r["sats"] is not None else "",
                            r["status"] if r else "sin escanear"])
        self._log(f"CSV exportado: {p}")

    # ---------------- eventos
    def _on_close(self):
        """Cierra la app de forma limpia: detiene escaneos, procesos y tareas programadas."""
        self._closing = True
        try:
            if self._srv_after:
                self.root.after_cancel(self._srv_after)
        except (ValueError, tk.TclError):
            pass
        self._srv_after = None
        if self.proc:
            try:
                self.proc.kill()
            except OSError:
                pass
            self.proc = None
        self.root.destroy()

    def _poll(self):
        if self._closing:
            return
        try:
            while True:
                ev = self.events.get_nowait()
                kind = ev[0]
                if kind == "log":
                    self._log(ev[1])
                elif kind == "scan_done":
                    ev = list(ev) + [None] * (6 - len(ev))
                    _, idx, utxos, sats, status, details = ev[:6]
                    details = details or []
                    self.results[idx] = {"utxos": utxos, "sats": sats, "status": status,
                                         "details": details}
                    if details:
                        self.last_utxos_details = details
                    funds = fmt_btc(sats) if sats is not None else "no detectado"
                    tag = "funds" if (sats or utxos) else "warn"
                    a = self.accounts[idx]
                    self.table.item(str(idx), tags=(tag,), values=(
                        a["folder"], a["pdf_name"], mask(a["code"]), utxos, funds, status))
                    self._recalc_totals()
                    self.progress.stop()
                    self.scan_btn.configure(state="normal")
                    self.stop_btn.configure(state="disabled")
                    self.status_var.set("Preparado.")
                    self._log(f"Resultado {a['folder']}: {utxos} UTXO(s), fondos {funds}.")
                    if details:
                        for d in details:
                            self._log(f"  UTXO detectado: {d['sats']:,} sats en {d['address']}")
                        self._log(f"  Total detectado en el detalle: "
                                  f"{sum(d['sats'] for d in details):,} sats.")
                    if sats == 0 and not utxos:
                        self._log("El recovery-tool informó que el escaneo terminó sin fondos (saldo cero).")
                    elif sats is None and not utxos:
                        self._log("El escaneo no produjo un saldo interpretable. Revisa los mensajes anteriores del recovery-tool.")
                    if (sats is not None and sats > 0) or utxos > 0:
                        self._log("Se detectaron fondos/UTXOs: mostrando opciones Bitcoin y comisión manual.")
                        self.table.selection_set(str(idx))
                        self.table.focus(str(idx))
                        self._log("El escaneo es de solo lectura: no se inicia ninguna transacción automáticamente.")
                elif kind == "scan_all_done":
                    _, n = ev
                    self._log(f"Escaneo de todas las cuentas finalizado ({n} cuenta(s)).")
                elif kind == "transfer_done":
                    _, status = ev
                    self.transfer_btn.configure(state="normal")
                    if hasattr(self, "extract_btn"):
                        self.extract_btn.configure(state="normal")
                    if hasattr(self, "transaction_tab_btn"):
                        self.transaction_tab_btn.configure(state="normal")
                    self.status_var.set("Preparado.")
                    self._log(status)
                    messagebox.showinfo(APP_NAME, status + "\nConsulta la consola para comprobar el resultado y el TXID.")
                elif kind == "server":
                    _, i, r = ev
                    self.server_state[i] = r
                    line = self.server_lines[i]
                    self.srv_table.item(str(i), tags=("ok" if r["ok"] else "bad",), values=(
                        line, "ONLINE" if r["ok"] else "FALLO",
                        f"{r['latency']} ms" if r["latency"] is not None else "",
                        r["height"], r["version"], r["error"]))
                elif kind == "servers_done":
                    ok = sum(1 for r in self.server_state.values() if r["ok"])
                    heights = [int(r["height"]) for r in self.server_state.values()
                               if r["ok"] and str(r["height"]).isdigit()]
                    self.v_servers.set(f"{ok} / {len(self.server_lines[:MAX_SERVERS])}")
                    if heights:
                        self.v_height.set(f"{max(heights):,}".replace(",", "."))
                    if ok != self._last_ok:
                        self._log(f"Servidores: {ok} en línea.")
                        self._last_ok = ok
                    self._srv_busy = False
                    if not self._closing:
                        self._srv_after = self.root.after(60000, self.check_servers)   # reconexión automática
        except queue.Empty:
            pass
        if not self._closing:
            try:
                self.root.after(100, self._poll)
            except tk.TclError:
                self._closing = True

def main(argv=None):
    """Punto de entrada: GUI por defecto, con --version y --help para diagnóstico."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--version" in argv or "-V" in argv:
        print(APP_NAME)
        return 0
    if any(a in ("-h", "--help", "-?") for a in argv):
        print(
            f"{APP_NAME}\n\n"
            "Uso:\n"
            f"  python {Path(__file__).name}            Abre la interfaz gráfica\n"
            f"  python {Path(__file__).name} --version  Muestra la versión\n\n"
            "Requisitos: Python 3.10+ con Tkinter y el binario recovery-tool\n"
            "(oficial de Muun; colócalo en bin/recovery-tool.exe o selecciónalo con BUSCAR…)."
        )
        return 0
    if tk is None:
        print(
            "ERROR: este Python no incluye Tkinter. Instala la versión oficial de python.org "
            "(marca «tcl/tk and IDLE») o ejecuta en un entorno con Tk.\n"
            "Sin Tkinter solo están disponibles las funciones de línea de comandos y las pruebas.",
            file=sys.stderr,
        )
        return 2
    root = tk.Tk()
    App(root)
    root.mainloop()
    return 0
