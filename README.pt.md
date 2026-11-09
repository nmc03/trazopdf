# TrazoPDF

[Español](README.es.md) · [English](README.md) · [Français](README.fr.md) · [Deutsch](README.de.md) · **Português**

Editor de PDF gratuito e de código aberto para Windows. Serve para as tarefas habituais com arquivos PDF — ler, localizar, anotar, preencher formulários, unir, dividir, tarjar ou converter — sem enviar os documentos a nenhum serviço online.

É uma alternativa simples para o uso diário do Adobe Acrobat. Não pretende igualar todas as suas funções: ficam de fora os serviços na nuvem, os fluxos de envio de assinaturas e várias funções especializadas. As limitações concretas de cada função estão descritas em [docs/FEATURES.md](docs/FEATURES.md).

![TrazoPDF com tema claro](docs/screenshots/editor-light.png)

![TrazoPDF com tema escuro](docs/screenshots/editor-dark.png)

## Principais recursos

- Leitura com zoom, exibição contínua e de duas páginas, busca e substituição de texto, e marcadores.
- Seleção de texto por caracteres, palavras e linhas, com cópia.
- Edição de texto e de blocos de PDF existentes, e escrita direta sobre a página.
- Imagens: selecionar, mover, redimensionar, substituir e excluir.
- Anotações: realce, sublinhado, riscado, notas com respostas e estado, formas, linhas, setas, caixas de texto e tinta.
- Links web, de e-mail e para páginas internas.
- Páginas: organizar, excluir, duplicar, combinar, dividir, extrair, cortar e girar.
- Formulários AcroForm: criar campos e preenchê-los sobre a página.
- Tarjas aplicadas, busca de dados sensíveis para tarjar, metadados, anexos e limpeza do documento.
- Anonimizar documento (Segurança): detecta dados pessoais, gera uma cópia nova, verifica essa cópia e entrega um relatório.
- Cabeçalhos e rodapés, numeração Bates, carimbos, rótulos de página, nivelamento, redução de tamanho, verificação do documento e comparação de texto.
- Senhas e criptografia AES-256.
- Assinatura digital com certificado próprio no formato PKCS#12, invisível ou com aparência visível, com várias assinaturas e validação local (sem verificar revogação; não é uma assinatura qualificada eIDAS).
- OCR para digitalizações incluído no programa, sem instalar nada: espanhol, inglês, francês, alemão e português, com endireitamento e detecção de orientação.
- Processamento em lote com receitas, também pela linha de comando.
- Conversão de Office para PDF com LibreOffice, e exportação de PDF para DOCX, XLSX e PPTX.
- Comparação visual de dois PDFs com relatório em ZIP.
- Desfazer e refazer durante a sessão.
- Vários PDFs abertos em abas, com salvamento automático e recuperação de alterações não salvas, cópia `.bak` opcional, Salvar cópia e Reverter.
- Medição de distâncias, camadas opcionais e ações guiadas para tarefas frequentes.
- Atalhos de teclado consultáveis com F1; por exemplo `F` para Preencher e assinar e `K` para Criar campo.
- Interface em espanhol, inglês, francês, alemão e português (Ajuda > Idioma, ou o idioma do sistema).

O guia completo de uso está no [manual do usuário](docs/manual/pt.md).

Consulte [docs/FEATURES.md](docs/FEATURES.md) para o escopo e os limites de cada área. As alterações de cada versão estão no [CHANGELOG](CHANGELOG.md).

## Processamento em lote

**Ferramentas > Processar vários PDFs…** aplica uma receita (lista ordenada de passos) a vários arquivos sem alterar os originais. Passos disponíveis: anonimizar, OCR, otimizar, limpar metadados e conteúdo oculto, marca d'água, numerar páginas, numeração Bates, girar, cortar margens, assinar com certificado e exportar texto. As receitas podem ser salvas, importadas e exportadas como `.json`, e há três predefinidas: *Anonimizar e arquivar*, *Digitalização para PDF pesquisável* e *Reduzir e limpar*.

Também é possível usar sem janela, por exemplo para automatizar um scanner:

```
"TrazoPDF.exe" --batch receta.json --in C:\Escaneos --out C:\Salida --recursive --on-conflict renombrar
"TrazoPDF.exe" --watch C:\Entrada --recipe receta.json --out C:\Salida
```

`--on-conflict` aceita `renombrar` (padrão), `omitir` e `sobrescribir`; `--interval` altera os segundos entre as verificações de `--watch` (5 por padrão). O código de saída é 0 se tudo correu bem, 1 se algum arquivo falhou e 2 se o uso estiver incorreto. O relatório é exibido e salvo como `batch-report.json` na pasta de saída. Se a receita assinar com certificado, a senha é lida da variável de ambiente `PDFEDITOR_SIGN_PASSWORD`. Os detalhes estão no [manual](docs/manual/pt.md#lotes-e-receitas).

## Baixar e instalar

As versões publicadas estão na página de [Releases](../../releases). Há duas formas de instalar:

- **Instalador** (`TrazoPDF-x.y.z-setup.exe`): instala para o seu usuário sem permissões de administrador. Você pode escolher instalar para todos os usuários do computador. Cria o atalho no menu Iniciar e, se marcar a opção, na área de trabalho. Registra o aplicativo em «Abrir com» para os PDFs, sem alterar seu programa padrão.
- **Pasta portátil** (`TrazoPDF-x.y.z-windows.zip`): descompacte o arquivo e execute `TrazoPDF.exe`. Não requer instalação.

Confira a integridade do arquivo baixado com o arquivo `SHA256SUMS.txt` da mesma versão.

Requisitos: Windows 10 ou 11 de 64 bits.

> **Sem assinatura.** O instalador e o executável não são assinados com certificado de código, então o Windows SmartScreen pode avisar de «editor desconhecido». Se você baixou o arquivo da página oficial de Releases, escolha *Mais informações* e depois *Executar mesmo assim*, e confira antes a soma com `SHA256SUMS.txt`.

## Compilar a partir do código-fonte

É necessário Python 3.13 para Windows.

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pdf_editor
```

Para gerar a pasta do aplicativo:

```powershell
.\build.ps1
```

A saída fica em `dist\TrazoPDF\`, com `TrazoPDF.exe` e um arquivo `SHA256SUMS.txt` ao lado da pasta. Para criar o instalador é necessário o [Inno Setup 6](https://jrsoftware.org/isinfo.php):

```powershell
.\installer\build-installer.ps1
```

O script procura `ISCC.exe` na instalação do Inno Setup e, se não o encontrar, você pode informar o caminho na variável de ambiente `INNO_SETUP_ISCC`. O instalador é criado em `installer\Output\`.

Os testes são executados sem janelas visíveis:

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python.exe -m pytest -q
```

## Dependências externas opcionais

- **LibreOffice** (não incluído): conversão de documentos do Office para PDF. Só é necessário para essa função. Download: https://www.libreoffice.org/
- **Tesseract OCR**: não é mais uma dependência externa na versão instalada nem na portátil, que o incluem com os modelos de espanhol, inglês, francês, alemão e português. Só ao executar a partir do código-fonte ele precisa estar instalado e localizável (os modelos adicionais são baixados com `tools/fetch_tessdata.ps1`). Download: https://github.com/UB-Mannheim/tesseract/wiki

## Atalhos de teclado

| Atalho | Ação |
| --- | --- |
| `Ctrl+O` | Abrir |
| `Ctrl+S` | Salvar |
| `Ctrl+Shift+S` | Salvar como |
| `Ctrl+Z` | Desfazer |
| `Ctrl+Shift+Z` | Refazer |
| `Ctrl+Y` | Refazer |
| `Ctrl+A` | Selecionar tudo (miniaturas ou texto, conforme o foco) |
| `Ctrl+Tab` / `Ctrl+Shift+Tab` | Alternar entre abas de documento |
| `Alt+1` a `Alt+9` | Ir para a aba indicada |
| `Ctrl+W` | Fechar o documento atual |
| `F1` | Atalhos de teclado (Ajuda) |
| `Ctrl+E` | Editar PDF |
| `Ctrl+F` | Localizar |
| `F3` / `Shift+F3` | Próximo resultado / anterior |
| `Ctrl+R` | Girar |
| `Ctrl+P` | Imprimir |
| `Ctrl+C` | Copiar texto selecionado |
| `Ctrl+Enter` | Aplicar o texto que você está digitando |
| `Esc` | Cancelar a digitação em curso |
| `F2` | Editar o bloco selecionado |
| `Del` | Excluir o elemento selecionado |
| `Ctrl` + roda do mouse | Alterar o zoom |

## Privacidade

O TrazoPDF funciona no seu computador. Não tem contas, telemetria nem verificação de atualizações, e não envia seus documentos para nenhum lugar. A única conexão de rede acontece quando você abre um link que você mesmo clica. Os detalhes estão em [PRIVACY.md](PRIVACY.md).

## Licença

O TrazoPDF é distribuído sob a [GNU Affero General Public License v3.0 ou posterior](LICENSE) (AGPL-3.0-or-later). Essa licença é necessária porque o PyMuPDF, uma de suas bibliotecas, está sob AGPL-3.0. As licenças das demais bibliotecas estão em [THIRD-PARTY.md](THIRD-PARTY.md).

É uma implementação independente. Não contém código, interface nem recursos gráficos da Adobe.

## Contribuir

Contribuições são bem-vindas. Antes de começar, leia o [CONTRIBUTING.md](CONTRIBUTING.md) e o [código de conduta](CODE_OF_CONDUCT.md). Para reportar uma vulnerabilidade, siga o [SECURITY.md](SECURITY.md).
