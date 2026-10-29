# Como ler o código do EcoCycle

O projeto executa em dois lugares: o computador interpreta as imagens e
gerencia a operação; a ESP32 recebe instruções e aciona os motores. O navegador
apresenta os resultados e envia as ações do operador ao computador.

Os comentários no código explicam as funções, as entradas, o estado compartilhado
e os motivos dos bloqueios. Eles não alteram os parâmetros nem o funcionamento.

## Ordem sugerida de leitura

1. [config.py](config.py): ajustes de instalação e parâmetros da operação.
2. [app.py](app.py): ponto de entrada, páginas e rotas HTTP.
3. [triage.py](triage.py): escolha do lote e autorização explícita para operar.
4. [vision.py](vision.py): da captura da câmera aos objetos com IDs.
5. [sorting.py](sorting.py): da peça confirmada ao comando de separação.
6. [websocket_server.py](websocket_server.py): troca de comandos e confirmações.
7. [EcoCycleClient.ino](esp32/EcoCycleClient/EcoCycleClient.ino): execução na ESP32.
8. Simulações e interface, descritas abaixo.

## Mapa dos arquivos Python

| Arquivo | Responsabilidade | Relação com os demais |
|---|---|---|
| `config.py` | Rede, GPIOs, curso e pulsos do servo, tempos, lotes e parâmetros de visão/simulação. | É importado pelos outros módulos; não conecta à rede por conta própria. |
| `app.py` | Servidor Flask, páginas, API JSON e transmissão do vídeo processado. | Inicializa a captura e registra os WebSockets com os controladores compartilhados. |
| `triage.py` | Selecionar, iniciar, pausar e concluir a operação de um lote. | Decide quando visão e separação podem contabilizar peças e criar comandos. |
| `vision.py` | Receber quadros, detectar cores na ROI, rastrear IDs e desenhar resultados. | Usa parser, buffer e filtro de fundo; envia observações para separação e peso. |
| `mjpeg.py` | Extrair JPEGs de pacotes de rede fragmentados. | Entrega bytes completos ao decodificador do OpenCV na visão. |
| `camera_buffer.py` | Manter somente o último quadro pendente. | Separa a velocidade de captura da velocidade de processamento sem criar fila. |
| `background.py` | Aprender o cenário vazio e ignorar regiões que já estavam coloridas. | Produz a máscara de mudanças aceita pelo detector. |
| `sorting.py` | Confirmar IDs e manter um único ciclo ativo de separação. | Produz `sort_cycle`, que o WebSocket envia à placa; aguarda `done` ou `error`. |
| `websocket_server.py` | Monitoramento e canal exclusivo de comandos para uma ESP32. | Valida handshake/sessão, transmite permissões e recebe ACKs/telemetria. |
| `batch_weights.py` | Simular peso por peça, somar materiais e fechar o total do lote. | Recebe IDs da visão ou eventos pela API local; não consulta balança. |
| `temperature.py` | Simular aquecimento/resfriamento e manter o bloqueio térmico. | Usa telemetria da ESP32 e valida a liberação manual solicitada pela API. |
| `motion.py` | Calcular a força fictícia e a velocidade exibida. | Usa peso processado e estado da esteira; não regula o motor físico. |
| `generate_esp32_config.py` | Gerar constantes C++ a partir da configuração Python. | Produz os headers dos dois sketches; não compila nem grava a placa. |

## Um ciclo completo

1. `python app.py` gera as configurações da placa, inicia a visão e abre o servidor.
2. A visão registra o fundo com a esteira vazia. O operador escolhe um lote.
3. O clique em **Iniciar triagem** passa pelas validações da API e de `triage.py`.
4. O WebSocket envia a autorização à ESP32, que liga a esteira se os bloqueios permitirem.
5. Uma nova peça dentro da ROI recebe um ID. A mesma cor precisa ser confirmada
   em quadros consecutivos antes de gerar comando ou peso simulado.
6. `sorting.py` cria um `sort_cycle` para cores com destino configurado. O peso
   usa sua própria confirmação e não é uma medição nem confirmação da queda da peça.
7. A ESP32 para o motor, aguarda acomodação, aplica o pulso do servo, espera o
   posicionamento e tenta retomar. Pausa, desconexão ou trava térmica impedem a retomada.
8. O ACK libera o ciclo atual. A mesma peça não gera outra instrução enquanto
   permanecer com o mesmo ID. Não existe fila de materiais.
9. O lote fecha ao atingir o peso total simulado. O controlador aguarda o ciclo
   ativo e o transporte final configurado antes de retirar a autorização do motor.

## Interface

- [static/lotes.html](static/lotes.html): primeira tela; consulta o catálogo e
  seleciona um lote. Selecionar e navegar não iniciam o motor.
- [static/index.html](static/index.html): dashboard; mostra vídeo, ROI, detecções,
  indicadores e pesos. Usa a API HTTP para iniciar, pausar, registrar fundo e
  liberar o bloqueio térmico. Consulta o estado periodicamente, sem controlar GPIOs.
- O CSS está no bloco `<style>` de cada página; o JavaScript está no bloco
  `<script>`. Os comentários diferenciam apresentação, eventos e comunicação.

## Arquivos da ESP32

| Arquivo | Finalidade |
|---|---|
| `esp32/EcoCycleClient/EcoCycleClient.ino` | Firmware principal. `setup()` prepara hardware e rede; `loop()` atende mensagens e avança o ciclo por tempo. |
| `esp32/EcoCycleClient/EcoCycleConfig.h` | Constantes geradas. Rede, pinos e tempos são copiados de `config.py` na geração. |
| `esp32/TesteServo/TesteServo.ino` | Diagnóstico temporário do servo, com esteira parada e sem rede/câmera. Substitui o firmware principal enquanto estiver gravado. |
| `esp32/TesteServo/EcoCycleConfig.h` | Configuração do diagnóstico, sem credenciais de rede. |

Edite os valores em `config.py`. Alterações destinadas à placa precisam de nova
geração, compilação e gravação. O cabeçalho explica as unidades: GPIO, Hz,
microssegundos, graus e milissegundos. Gerar um header não atualiza uma placa já gravada.

## Testes

Os testes usam objetos substitutos (*mocks*), relógios controlados e imagens
sintéticas. Os de WebSocket também abrem servidores locais, sem comandar a placa física.
Cada método de teste tem um comentário em português explicando a regra verificada.

| Arquivo | O que verifica |
|---|---|
| `tests/test_background.py` | Fundo fixo, exposição, ruído, ROI e peças novas. |
| `tests/test_camera_buffer.py` | Último quadro, atrasos e bloqueio de comandos/pesos antes do início. |
| `tests/test_mjpeg.py` | Fragmentação, imagens incompletas e recuperação do fluxo JPEG. |
| `tests/test_sorting.py` | Confirmação, destino, repetição, ACK, reconexão e telemetria. |
| `tests/test_batch_weights.py` | Faixas de peso, saldo, duplicatas, concorrência e API local. |
| `tests/test_temperature.py` | Aquecimento, resfriamento, duração ligada e expiração da telemetria. |
| `tests/test_thermal_motion.py` | Trava térmica, liberação manual e modelo fictício de carga/velocidade. |
| `tests/test_triage.py` | Escolha, início, pausa, conclusão e protocolo de autorização. |
| `tests/test_config_export.py` | Validação e geração das constantes da ESP32. |
| `tests/test_websocket.py` | Estado consistente entre HTTP e monitoramento WebSocket. |
| `tests/firmware/test_cycle.cpp` | Sketch real com relógio, pinos e comunicação substituídos; confere estados, pulsos e mensagens. |
| `tests/firmware/fakes/HostArduino.h` | Adapta `String`, relógio, GPIO e Serial para o teste no computador. |
| `tests/firmware/fakes/WiFi.h` | Simula Wi-Fi conectado, sem acessar uma rede real. |
| `tests/firmware/fakes/WebSocketsClient.h` | Registra textos enviados em vez de abrir um WebSocket real. |
| `tests/firmware/fakes/ESP32Servo.h` | Registra pulsos solicitados; não produz PWM físico. |

Para executar a suíte Python:

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

O teste C++ tem instruções próprias em [tests/firmware/README.md](tests/firmware/README.md).
Testes de software não comprovam alimentação, torque, frenagem ou alinhamento mecânico.

## Termos que aparecem nos comentários

| Termo | Significado neste projeto |
|---|---|
| ROI | Região da imagem onde a detecção é permitida. |
| HSV | Representação de cor usada pelos intervalos do detector. |
| ID de rastreamento | Associação temporária de uma peça entre quadros; pode mudar após perda/oclusão. |
| Lock / RLock / Condition | Recursos que coordenam acesso ao estado entre threads. RLock permite reentrada; Condition permite esperar um aviso. |
| Snapshot | Cópia do estado atual para consulta, sem entregar estruturas internas modificáveis. |
| Handshake | Identificação inicial que verifica compatibilidade do firmware. |
| Sessão e command_id | Identificam a execução do servidor e cada ciclo, evitando aceitar confirmações de outra operação. |
| ACK | Resposta da ESP32 ao comando. `done` confirma a sequência do código, não o alinhamento físico. |
| Timeout | Prazo máximo antes de considerar um dado vencido ou uma resposta ausente. |
| PWM / pulso em µs | Sinal usado para solicitar a posição do servo; os limites precisam de calibração. |

`requirements.txt` lista as bibliotecas instaladas no ambiente Python e explica
a finalidade de cada uma. `.vscode/settings.json` é uma preferência do editor;
não participa do ciclo da esteira. `.venv/` contém bibliotecas de terceiros e
`__pycache__/` contém arquivos compilados automaticamente; não são fontes para comentar.

Peso, temperatura e velocidade continuam simulados. Os materiais representam
associações por cor. O backend externo ainda não está integrado: o catálogo de
lotes vem da configuração local ou da API local já disponível.
