import base64
import os
import re
import shutil
import sys
import time
import unicodedata
from pathlib import Path

import fitz
from openai import OpenAI

SYSTEM_PROMPT = (
    "Você é um extrator especializado em recibos Pix. "
    "Retorne apenas o nome padronizado no formato pix_[favorecido]_[valor], sem explicações."
)

USER_PROMPT = (
    "Analise a imagem deste comprovante e retorne estritamente o formato: "
    "pix_[nome_do_favorecido]_[valor]. Sem acentos, sem letras maiúsculas, "
    "sem extensão, sem crases."
)

DPI_RENDERIZACAO = 150
MAX_TENTATIVAS_LLM = 3
LLM_TIMEOUT_SEGUNDOS = 180.0


def carregar_configuracao():
    return {
        "input_dir": Path(os.environ.get("INPUT_DIR", "/app/input")),
        "output_dir": Path(os.environ.get("OUTPUT_DIR", "/app/output")),
        "llm_base_url": os.environ.get("LLM_BASE_URL", "http://host.docker.internal:11434/v1"),
        "llm_model": os.environ.get("LLM_MODEL", "gemma4:12b"),
        "llm_api_key": os.environ.get("LLM_API_KEY", "ollama"),
    }


def listar_arquivos_pdf(pasta):
    return sorted(
        (
            arquivo
            for arquivo in pasta.iterdir()
            if arquivo.is_file() and arquivo.suffix.lower() == ".pdf"
        ),
        key=lambda arquivo: arquivo.name,
    )


def renderizar_primeira_pagina_base64(caminho_pdf):
    with fitz.open(caminho_pdf) as documento:
        pagina = documento.load_page(0)
        pixmap = pagina.get_pixmap(dpi=DPI_RENDERIZACAO)
        png_bytes = pixmap.tobytes("png")
    return base64.b64encode(png_bytes).decode("utf-8")


def solicitar_nome_na_llm(cliente, modelo, imagem_base64):
    ultima_excecao = None
    for tentativa in range(1, MAX_TENTATIVAS_LLM + 1):
        try:
            resposta = cliente.chat.completions.create(
                model=modelo,
                temperature=0.0,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": USER_PROMPT},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{imagem_base64}"
                                },
                            },
                        ],
                    },
                ],
            )
            return resposta.choices[0].message.content
        except Exception as excecao:
            ultima_excecao = excecao
            print(
                f"    Tentativa {tentativa}/{MAX_TENTATIVAS_LLM} falhou: {excecao}",
                flush=True,
            )
            if tentativa < MAX_TENTATIVAS_LLM:
                time.sleep(3 * tentativa)
    raise RuntimeError(
        f"Falha ao consultar a LLM após {MAX_TENTATIVAS_LLM} tentativas: {ultima_excecao}"
    )


def sanitizar_nome(nome_bruto):
    nome = nome_bruto.strip().strip("\"'")
    nome = nome.replace("`", "")
    nome = unicodedata.normalize("NFKD", nome)
    nome = "".join(c for c in nome if not unicodedata.combining(c))
    nome = nome.lower()
    nome = nome.replace("&", " e ")
    nome = nome.replace(" ", "_")
    nome = re.sub(r"[^a-z0-9_\-]", "", nome)
    nome = re.sub(r"_+", "_", nome)
    nome = nome.strip("_-")
    if nome and not nome.startswith("pix_"):
        nome = f"pix_{nome}"
    return nome


def resolver_caminho_destino(pasta_saida, nome_base):
    candidato = pasta_saida / f"{nome_base}.pdf"
    sufixo = 1
    while candidato.exists():
        candidato = pasta_saida / f"{nome_base}_{sufixo}.pdf"
        sufixo += 1
    return candidato


def main():
    configuracao = carregar_configuracao()
    pasta_entrada = configuracao["input_dir"]
    pasta_saida = configuracao["output_dir"]

    print(f"INPUT_DIR={pasta_entrada} | OUTPUT_DIR={pasta_saida}", flush=True)
    print(
        f"LLM_BASE_URL={configuracao['llm_base_url']} | LLM_MODEL={configuracao['llm_model']}",
        flush=True,
    )

    if not pasta_entrada.exists():
        print(f"Pasta de entrada '{pasta_entrada}' não existe. Encerrando.", flush=True)
        return 1

    pasta_saida.mkdir(parents=True, exist_ok=True)

    arquivos_pdf = listar_arquivos_pdf(pasta_entrada)

    if not arquivos_pdf:
        print(
            f"Nenhum arquivo PDF encontrado em '{pasta_entrada}'. Pasta vazia. Encerrando.",
            flush=True,
        )
        return 0

    total = len(arquivos_pdf)
    print(f"Encontrados {total} arquivo(s) PDF para processar.", flush=True)

    cliente = OpenAI(
        base_url=configuracao["llm_base_url"],
        api_key=configuracao["llm_api_key"],
        timeout=LLM_TIMEOUT_SEGUNDOS,
    )
    modelo = configuracao["llm_model"]

    sucessos = 0
    falhas = 0

    for index, arquivo_pdf in enumerate(arquivos_pdf, start=1):
        print(
            f"[Iteração {index}/{total}] Processando arquivo atual: {arquivo_pdf.name}",
            flush=True,
        )

        try:
            imagem_base64 = renderizar_primeira_pagina_base64(arquivo_pdf)

            sugestao_bruta = solicitar_nome_na_llm(cliente, modelo, imagem_base64)
            novo_nome = sanitizar_nome(sugestao_bruta or "")

            if not novo_nome:
                novo_nome = sanitizar_nome(arquivo_pdf.stem) or f"pix_comprovante_{index}"
                print(
                    f"    Retorno da LLM vazio/inválido. Usando nome alternativo: {novo_nome}",
                    flush=True,
                )

            caminho_destino = resolver_caminho_destino(pasta_saida, novo_nome)
            shutil.move(str(arquivo_pdf), str(caminho_destino))

            sucessos += 1
            print(
                f"[Iteração {index}/{total}] Sucesso: '{arquivo_pdf.name}' renomeado "
                f"para '{caminho_destino.name}' e movido para '{caminho_destino}'",
                flush=True,
            )
        except Exception as excecao:
            falhas += 1
            print(
                f"[Iteração {index}/{total}] Erro ao processar '{arquivo_pdf.name}': {excecao}",
                flush=True,
            )

    print(
        f"Processamento concluído: {sucessos} sucesso(s), {falhas} falha(s), total {total}.",
        flush=True,
    )
    return 0 if falhas == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
