"""
Limitador de banda por balde de fichas.

POR QUE. Pausar entre arquivos derruba a média mas não o pico: o
download em si continua a toda velocidade e satura o enlace pelos
segundos que durar. Medido nesta máquina: média de 11,6 Mbit/s com
rajadas de 82 Mbit/s, o bastante para travar uma videochamada num
Wi-Fi de 2,4 GHz.

O limite tem de agir DURANTE a transferência, não entre elas.

COMO. Balde de fichas clássico: fichas entram a uma taxa fixa, cada
byte recebido gasta uma ficha, e quem fica sem ficha espera. O balde
guarda no máximo um segundo de tráfego, o que permite pequenas
rajadas sem deixar a média subir.

O limitador é compartilhado por todas as threads, então o teto vale
para o processo inteiro, não por thread — que é justamente o erro
que fez "6 workers" virarem 41 conexões.
"""
import threading
import time


class Limitador:
    def __init__(self, mbit_s):
        self.taxa = mbit_s * 1_000_000 / 8      # bytes por segundo
        self.balde = self.taxa                  # começa cheio
        self.teto = self.taxa                   # guarda 1 s de rajada
        self.t = time.monotonic()
        self.trava = threading.Lock()
        self.total = 0

    def consumir(self, n):
        """Espera até haver ficha para n bytes."""
        while n > 0:
            with self.trava:
                agora = time.monotonic()
                self.balde = min(self.teto,
                                 self.balde + (agora - self.t) * self.taxa)
                self.t = agora
                if self.balde >= 1:
                    gasto = min(n, int(self.balde))
                    self.balde -= gasto
                    self.total += gasto
                    n -= gasto
                    continue
                espera = (1 - self.balde) / self.taxa
            time.sleep(min(espera, 0.5))

    def mbit_s_medio(self, desde):
        s = time.monotonic() - desde
        return self.total * 8 / s / 1e6 if s > 0 else 0.0


_global = None


def configurar(mbit_s):
    global _global
    _global = Limitador(mbit_s) if mbit_s and mbit_s > 0 else None
    return _global


def baixar(sessao_get, url, timeout=1800, pedaco=64 * 1024):
    """GET que respeita o limitador global. Devolve os bytes."""
    if _global is None:
        r = sessao_get(url, timeout=timeout)
        r.raise_for_status()
        return r.content

    r = sessao_get(url, timeout=timeout, stream=True)
    r.raise_for_status()
    partes = []
    for p in r.iter_content(chunk_size=pedaco):
        if p:
            _global.consumir(len(p))
            partes.append(p)
    return b"".join(partes)
