"""Injeta dados e biblioteca no gabarito, produzindo um HTML autocontido.

Um arquivo só, sem servidor e sem CDN: o painel roda de pendrive, de
anexo de e-mail e de pasta de rede, que é como ele efetivamente
circula dentro da empresa.

POR QUE O LEAFLET VAI EMBUTIDO
------------------------------
Puxar a biblioteca de CDN deixaria o mapa em branco em qualquer
máquina sem internet ou atrás de proxy corporativo — e sem erro
visível para quem abre o arquivo. Os 162 kB do Leaflet somam 2,7% a
um painel de 6 MB; é preço barato por abrir em qualquer lugar.

O CSS do Leaflet referencia PNGs (`marker-icon.png`, `layers.png`) que
não existem aqui. Nenhum é requisitado: os ativos usam `circleMarker`,
que é vetor, e o controle de camadas fica aberto — fechado, ele
mostraria justamente o ícone que falta.

O HTML montado é artefato de construção e não é versionado.
"""
import zipfile
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config as C

D = Path(__file__).resolve().parent
html = (D / "app.html").read_text(encoding="utf-8")

partes = {
    "__LEAFLET_CSS__": (D / "vendor" / "leaflet.css").read_text(encoding="utf-8"),
    "__LEAFLET_JS__": (D / "vendor" / "leaflet.js").read_text(encoding="utf-8"),
    "__DADOS__": (C.DIR_SAIDA / "painel_seca.json").read_text(encoding="utf-8"),
}

for marca, txt in partes.items():
    if marca not in html:
        raise ValueError(f"marca {marca} ausente do gabarito")
    # `</` dentro do conteúdo encerraria a tag <script> cedo demais e o
    # painel abriria em branco, sem erro no console.
    html = html.replace(marca, txt.replace("</", "<\\/"))

saida = C.DIR_SAIDA / "painel_seca.html"
saida.write_text(html, encoding="utf-8")
print(f"{saida.name}: {saida.stat().st_size / 1e6:.2f} MB")

# Versão para envio. O painel é quase todo coordenada em texto, que
# comprime a um sexto — 6,2 MB viram menos de 1 MB, abaixo do limite
# de anexo da maioria dos servidores corporativos, que costuma ser 10
# ou 25 MB mas conta o acréscimo de 33% da codificação base64 do
# e-mail. ZIP e não 7z ou rar: abre com clique duplo no Windows, no
# macOS e no Linux, sem instalar nada.
zipado = C.DIR_SAIDA / "painel_seca.zip"
with zipfile.ZipFile(zipado, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    z.write(saida, arcname=saida.name)
print(f"{zipado.name}: {zipado.stat().st_size / 1e6:.2f} MB  "
      f"({100 * zipado.stat().st_size / saida.stat().st_size:.0f}% do original)")
