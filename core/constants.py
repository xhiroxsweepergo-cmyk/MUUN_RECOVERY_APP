import json
from pathlib import Path

APP_NAME = "MUUN RECOVERY PRO"
BG, PANEL, PANEL_ALT = "#101827", "#1b2738", "#243247"
ORANGE, WHITE, MUTED, GREEN, RED = "#ff9f43", "#f3f6fa", "#aab7c8", "#52d69a", "#ff7272"

MAX_ENTRIES = 10000
MAX_SERVERS = 300
SERVER_TIMEOUT = 6.0
CONNECT_TIMEOUT = 6.0
SCAN_TIMEOUT = 60 * 60
SERVERS_FILE = Path(__file__).resolve().parent.parent / "electrum_servers.json"
SEND_PHRASE = "AUTORIZO ENVIAR"
FEATURES = [
    ("Electrum", "Conexiones reales y estado de servidores."),
    ("Recovery Scan", "Direcciones derivadas y búsqueda de UTXO."),
    ("TXID / UTXO", "Importes, índices e historiales."),
    ("Transferencias", "Firma y autorización independiente."),
]
BANNER_TITLE = "RECUPERACIÓN Y TRANSFERENCIA SEPARADAS"
BANNER_TEXT = "Confirmación manual antes de firmar y transmitir cualquier transacción."

DEFAULT_SERVERS = [
    "electrum.coinext.com.br:50002:s",
    "fulcrum.sethforprivacy.com:50002:s",
    "mainnet.foundationdevices.com:50002:s",
    "btc.lastingcoin.net:50002:s",
    "vmd71287.contaboserver.net:50002:s",
    "de.poiuty.com:50002:s",
    "electrum.jochen-hoenicke.de:50006:s",
    "btc.cr.ypto.tech:50002:s",
    "e.keff.org:50002:s",
    "vmd104014.contaboserver.net:50002:s",
    "e2.keff.org:50002:s",
    "fulcrum.grey.pw:51002:s",
    "fortress.qtornado.com:443:s",
    "f.keff.org:50002:s",
    "2ex.digitaleveryware.com:50002:s",
    "electrum.petrkr.net:50002:s",
    "electrum.stippy.com:50002:s",
    "electrum0.snel.it:50002:s",
    "ru.poiuty.com:50002:s",
    "electrum.privateservers.network:50002:s",
    "btc.electroncash.dk:60002:s",
    "bitcoin.aranguren.org:50002:s",
    "electrum.bitcoinserver.nl:50514:s",
    "btc.prompt.cash:61002:s",
    "fulc.bot.nu:50002:s",
    "bolt.schulzemic.net:50002:s",
    "node1.btccuracao.com:50002:s",
    "xtrum.com:50002:s",
    "electrum.bitaroo.net:50002:s",
    "btce.iiiiiii.biz:50002:s",
    "electrum.emzy.de:50002:s",
    "alviss.coinjoined.com:50002:s",
    "2azzarita.hopto.org:50002:s",
    "vmd104012.contaboserver.net:50002:s",
    "electrum.bitcoinlizard.net:50002:s",
    "btc.ocf.sh:50002:s",
    "bitcoins.sk:56002:s",
    "electrum-btc.leblancnet.us:50002:s",
    "helicarrier.bauerj.eu:50002:s",
    "electrum.neocrypto.io:50002:s",
    "caleb.vegas:50002:s",
    "smmalis37.ddns.net:50002:s",
    "electrum.kendigisland.xyz:50002:s",
    "electrum.hsmiths.com:50002:s",
    "vmd63185.contaboserver.net:50002:s",
    "blkhub.net:50002:s",
    "electrum.mmitech.info:50002:s",
    "elx.bitske.com:50002:s",
    "bitcoin.lu.ke:50002:s",
    "ex05.axalgo.com:50002:s",
    "walle.dedyn.io:50002:s",
    "eai.coincited.net:50002:s",
    "2electrumx.hopto.me:56022:s",
    "hodlers.beer:50002:s",
    "kareoke.qoppa.org:50002:s",
    "assuredly.not.fyi:50002:s",
    "electrumx.alexridevski.net:50002:s",
    "ragtor.duckdns.org:50002:s",
    "surely.not.fyi:50002:s",
    "btc.electrum.bitbitnet.net:50002:s",
    "gods-of-rock.screaminglemur.net:50002:s",
    "horsey.cryptocowboys.net:50002:s",
    "electrumx-btc.cryptonermal.net:50002:s",
    "electrum.coineuskal.com:50002:s",
    "electrum.blockstream.info:50002:s",
    "electrum.acinq.co:50002:s",
    "bitcoin.lukechilds.co:50002:s",
    "electrum.hodlister.co:50002:s",
    "electrum.bitcoinserver.nl:50002:s",
]
