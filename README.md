# ESP32: separar objetos por cor com dois servos posicionais

O computador interpreta a câmera e a ESP32 controla a esteira e o prato.
O ciclo é **identificar → parar a esteira → posicionar o recipiente →
retomar a esteira até identificar outra peça**. O controle
implementado usa **dois SG90 posicionais de 180° com eixos alinhados**. O servo B
de baixo gira o corpo do servo A de cima, somando até 360° no prato. O curso não
é contínuo. Veja montagem e calibração em [DOIS_SERVOS.md](DOIS_SERVOS.md).
Os materiais abaixo são uma associação configurada
por cor; não são identificados fisicamente pela câmera.

| Cor detectada | Recipiente | Material atribuído | Ângulo inicial |
|---|---|---|---|
| Laranja | A | Plástico | 0° |
| Verde-claro | B | Alumínio | 90° |
| Azul-claro | C | Metal | 180° |
| Roxo | D | Rejeito | 270° |

As quatro cores participam do ciclo de parada e posicionamento. Roxo/rejeito
usa 270° no prato, correspondentes a 135° em cada um dos dois SG90.

Esses ângulos representam posições do eixo que devem alinhar o recipiente
com a queda da esteira. A imagem não determina o zero nem o sentido do servo:
calibre `SORT_TARGETS` em `config.py` na montagem real. Verde e azul continuam
usando as mesmas faixas HSV anteriores (`Verde-claro` e `Azul-claro`).
O destino corresponde ao **ângulo total do prato**, dividido entre os dois SG90.
Por exemplo, 270° resultam em 135° em cada eixo. Edite o campo
`angle_deg` de cada cor no bloco `SORT_TARGETS` do `config.py`. Cada cor aceita
um valor próprio de 0 a 360°, inclusive valores decimais, como 90,5° (escreva
`90.5` no Python). Ajuste os ângulos à posição real dos recipientes.
Reinicie o Python para aplicar esses valores aos novos comandos. O firmware
recebe o ângulo no JSON; a tabela de cores permanece centralizada no servidor.

## Escolher lote e iniciar a triagem

Ao abrir `/`, a página mostra os lotes locais de demonstração definidos em
`AVAILABLE_BATCHES` no `config.py`. A integração com o backend continua
pendente. Também aparecem lotes cadastrados pela API local de simulação.

1. Clique em **Escolher lote** para reservar a seleção e abrir `/dashboard`.
2. Prepare a câmera e aguarde o fundo e a ESP32 estarem prontos.
3. Clique em **Iniciar triagem**. Só então o lote é iniciado para contabilização
   pela câmera e o servidor autoriza o motor.

Escolher o lote, abrir o dashboard, conectar a placa ou detectar uma cor não
ligam a esteira. **Pausar triagem** retira a autorização e preserva o progresso;
**Retomar triagem** precisa de novo clique. O botão **Lotes** pausa antes de
voltar à lista. Um lote incompleto deve ser concluído antes de iniciar outro.
Atualizar o dashboard não reinicia pesos nem cria nova autorização.

Quando o peso simulado chega ao total, o servidor aguarda a confirmação do
último posicionamento e mantém o transporte por `BATCH_FINISH_RUN_SECONDS`
(3 s) de funcionamento contínuo antes de parar. Calibre esse intervalo com a
distância da câmera até a saída e a velocidade real. Tempo parado por calor,
pausa ou falta de comunicação não conta como transporte final. A conclusão
e a parada não dependem de o navegador permanecer aberto.

O estado fica em memória: reiniciar o Python limpa a seleção e exige novo
início pelo operador. Uma reconexão de rede da placa pode retomar uma triagem
que o operador já havia iniciado, respeitando os bloqueios térmicos.

Rotas: `GET /api/lotes`, `POST /api/lotes/selecionar` com `loteId`,
`POST /api/triagem/iniciar` com o mesmo `loteId` e `POST /api/triagem/pausar`.
`/api/detections` inclui `triagem` com o lote, etapa, autorização e prontidão
da placa. O servidor rejeita início sem seleção, com lote de outra tela,
câmera indisponível, placa sem protocolo atualizado ou bloqueio térmico.

## Câmera fixa e captura do fundo

Ao iniciar o Python, mantenha a câmera fixa e a esteira sem carimbinhos por
`BACKGROUND_WARMUP_SECONDS` (padrão 2 segundos), com pelo menos
`BACKGROUND_MIN_FRAMES` quadros recebidos (padrão 10). A página
mostra quando a captura do fundo termina. Nesse período nenhuma detecção
é enviada para separação ou simulação de peso.

Depois, um contorno de cor só é aceito se a fração definida por
`BACKGROUND_MIN_CHANGED_RATIO` (padrão 60%) diferir do cenário registrado.
`BACKGROUND_DIFF_THRESHOLD` controla a sensibilidade à diferença de cor.
Esses valores ficam em `config.py`. O fundo fica congelado, para que uma
peça parada enquanto o servo gira continue sendo rastreada. As faixas HSV,
a ROI e a confirmação de três quadros continuam em uso.

As regiões coloridas vistas durante a captura inicial ficam bloqueadas,
mesmo se a exposição ou a cor registrada pela câmera mudar. A margem
`BACKGROUND_IGNORE_MARGIN_PX` (padrão 3 pixels) cobre variações nas bordas.
Restrinja a ROI à esteira: carimbinhos colocados sobre regiões bloqueadas
também podem ser ignorados. As regiões permanecem bloqueadas até recapturar
o fundo.

Se mover a câmera, mudar muito a iluminação ou alterar o cenário, retire os
carimbinhos e clique em **Registrar fundo novamente**. A rota
`POST /api/camera/background` solicita uma nova captura no próximo quadro;
durante a captura os resultados ficam vazios e novos IDs não são reutilizados.
Também é possível reiniciar o Python com a esteira vazia.
Uma reconexão do vídeo preserva o fundo. O filtro detecta mudanças e cores;
outro objeto novo da mesma cor dentro da ROI também pode ser reconhecido.
Não há classificação do formato dos carimbinhos.

## Servidor no computador

No terminal, dentro da pasta do projeto:

```powershell
if (-not (Test-Path -LiteralPath config.py)) {
    Copy-Item -LiteralPath config.example.py -Destination config.py
}
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

Em uma cópia nova do repositório, preencha a rede e confira a calibração no
`config.py` antes de executar `app.py`. O comando de cópia acima preserva uma
configuração local que já exista. `config.example.py` é o modelo versionado com
rede fictícia; `config.py`, `.env`, os headers gerados, o ambiente virtual e os
caches ficam fora do Git. Não coloque credenciais reais no modelo.

**Edite somente `config.py` para configurar o projeto.** Nele ficam:

- `CAMERA_URL`: vídeo do celular/câmera IP.
- `SERVER_PUBLIC_HOST`: IPv4 do computador na rede da placa.
- `HOST` e `PORT`: interface e porta do servidor.
- `ESP32_WIFI_SSID` e `ESP32_WIFI_PASSWORD`: Wi-Fi da placa.
- `SERVO_*`: pino, frequência, pulsos, curso e habilitação do servo.
- `CONVEYOR_*`: habilitação, pinos do L9110S e sentido do motor da esteira.
- `CONVEYOR_ESTIMATED_SPEED_M_S`: referência visual de velocidade em m/s; não regula o motor.
- `SORT_*`: recipientes, materiais, ângulos e tempos da separação.
- `WS_*`, `ESP32_*` e `CAMERA_*`: intervalos e limites de comunicação.
- `TEMP_*`: temperatura ambiente, teto e velocidades de aquecimento/resfriamento simulados.

Ao iniciar `app.py`, o projeto gera automaticamente
`esp32/EcoCycleClient/EcoCycleConfig.h`. O firmware inclui esse arquivo, sem
URLs ou credenciais escritas diretamente no `.ino`. Para gerar sem iniciar
o servidor:

```powershell
.\.venv\Scripts\python.exe generate_esp32_config.py
```

O `.h` é gerado: não o edite manualmente. Mudanças de Wi-Fi, IP/porta/rota ou
servo/esteira exigem **gerar novamente e regravar a ESP32**. Mudanças somente de câmera,
visão, associação de recipientes e tempos enviados nos comandos exigem
reiniciar o servidor. Após editar qualquer configuração da placa, gere o
arquivo antes de compilar. O servidor não atualiza sozinho uma placa já gravada.

O WebSocket de comandos usa a mesma porta do site:
`ws://IP_DO_COMPUTADOR:8000/ws/sorter`.
Use `ipconfig` para consultar o IPv4 do adaptador Wi-Fi/Ethernet conectado
à rede da ESP32. Não use `localhost`, `0.0.0.0` ou o IP do celular na placa.
Computador e ESP32 precisam se alcançar pela rede. Caso o Windows bloqueie a
conexão, permita o Python/porta TCP 8000 na rede privada pelo Firewall.

## Código da placa

1. Na Arduino IDE, selecione sua placa ESP32 e a porta USB.
2. Instale **WebSockets**, de Markus Sattler (Links2004), **ArduinoJson 7**, de Benoit Blanchon, e **ESP32Servo**.
3. Abra `EcoCycleClient/EcoCycleClient.ino`.
4. Preencha `ESP32_WIFI_SSID`, `ESP32_WIFI_PASSWORD` e `SERVER_PUBLIC_HOST` em `config.py` e gere `EcoCycleConfig.h`.
5. Configure o servo e o L9110S como descrito abaixo antes de acionar os motores.
6. Envie para a placa e abra o Monitor Serial em **115200 baud**.

### Servo e calibração

Em `config.py` (exportado automaticamente para `EcoCycleConfig.h`):

- `SERVO_PIN`: sinal do servo B de baixo, GPIO 18.
- `SERVO_TOP_PIN`: sinal do servo A de cima, GPIO 19. Confira sua placa.
- `SERVO_MIN_US`, `SERVO_MAX_US`, `SERVO_FREQUENCY_HZ`: consulte o datasheet
  do modelo e calibre. **500–2500 µs e 50 Hz são valores de exemplo**, não uma
  especificação confirmada do seu servo.
- `SERVO_TRAVEL_DEG` e `SERVO_TOP_TRAVEL_DEG`: 180° por eixo.
  A soma gera `PLATE_TRAVEL_DEG = 360°`; destinos além dessa soma são recusados.
- `SERVO_TOP_MIN_US`, `SERVO_TOP_MAX_US`: calibração independente do servo de cima.
- `SERVO_REVERSED`, `SERVO_TOP_REVERSED`: invertem o pulso de cada eixo conforme a montagem.
- `SERVO_CALIBRATED`: quando `False`, o firmware recebe os comandos mas
  responde `error` e não conecta o PWM. Configure os limites reais e então
  mude para `True`, gere o arquivo e regrave a placa para habilitar o acionamento.

A fração do curso total é aplicada aos dois eixos, respeitando cada calibração.
Com ambos em 180°, cada servo recebe metade do ângulo final. O firmware usa
`writeMicroseconds()`: a função `write()` da ESP32Servo limita ângulos a 180°.
Não use este firmware em um servo contínuo, no qual pulsos controlam velocidade.

Ligue cada sinal ao GPIO configurado, os servos a uma fonte compatível com os
dois atuadores e una o GND da fonte ao GND da ESP32. A ligação de potência dos servos
não passa pelo GPIO.

### Motor da esteira e L9110S

O firmware controla um canal do L9110S, com o motor TT ligado às saídas desse
canal. Os valores iniciais no `config.py` são:

| Conexão | Configuração | Valor inicial |
|---|---|---|
| Entrada IA do canal do driver | `CONVEYOR_PIN_IA` | GPIO 26 |
| Entrada IB do mesmo canal | `CONVEYOR_PIN_IB` | GPIO 25 |
| Sinal do servo B de baixo | `SERVO_PIN` | GPIO 18 |
| Sinal do servo A de cima | `SERVO_TOP_PIN` | GPIO 19 |
| Sentido do transporte | `CONVEYOR_FORWARD_IA_HIGH` | `True` |

Confirme os GPIOs disponíveis no seu modelo de ESP32 e adapte à fiação real.
Os quatro pinos devem ser diferentes. Motor TT é ligado ao driver; não ao GPIO.
Una o GND da ESP32 ao GND do driver e use alimentação compatível com o motor.
**IB não pode ficar flutuando.** As duas entradas precisam estar ligadas aos
GPIOs atuais do `config.py`, no mesmo canal do L9110S. Alterar o código não
substitui essa ligação.

Habilite `CONVEYOR_ENABLED = True` depois de conferir as ligações. Para iniciar
o transporte, `SERVO_CALIBRATED` também precisa estar em `True`. O firmware
deixa a esteira parada durante o boot, a conexão Wi-Fi e a seleção do lote.
A partida exige **Iniciar triagem** no dashboard. A direção usa IA alto/IB
baixo ou o inverso; a parada usa
as duas entradas baixas, conforme a [tabela do módulo L9110S](https://docs.sunfounder.com/projects/3in1-kit-r4/en/latest/components/component_l9110s.html).
Esta versão liga/desliga o motor; não regula a velocidade por PWM.

### Parada por temperatura crítica simulada

`TEMP_CRITICAL_C` (60 °C) trava a esteira. O servidor verifica a temperatura
no próprio loop do WebSocket, mesmo sem página aberta, e envia
`{"type":"thermal_control","session_id":"...","blocked":true}` à placa.
O firmware para o motor e impede a retomada automática por estado livre,
conclusão do posicionamento ou reconexão. Um posicionamento em andamento
pode terminar com a esteira parada.

Esfriar não libera o bloqueio. Quando a temperatura chega a `TEMP_RELEASE_C`
(50 °C) ou menos e a ESP32 confirma a parada, o painel habilita **Liberar
esteira após resfriamento**. Esse botão chama
`POST /api/conveyor/thermal/reset`. O servidor recusa com HTTP 409 se ainda
estiver quente ou sem confirmação recente da placa. A liberação envia
`thermal_control` com `blocked:false`; a esteira retoma quando estiver livre
e a triagem continuar autorizada. Liberar o calor não inicia uma triagem pausada.

O `hello` inclui `thermal_blocked` para não haver partida antes de conhecer
o bloqueio. A ESP32 repete esse estado em `conveyor_state` e `ack`. Um `hello`
de reconexão não remove um bloqueio local; a primeira telemetria permite ao
servidor recuperar esse bloqueio, inclusive após reiniciar o Python. Sem
fila, peças vistas durante a parada precisam ser confirmadas novamente
depois da liberação. A mesma peça já tratada não é repetida.

É necessário regravar o firmware atualizado para receber o comando térmico.
Os valores são de uma simulação de temperatura; não medem aquecimento real.
Temperatura e lote permanecem em memória no Python. Alterar os limites em
`config.py` exige reiniciar o servidor.

### Força e velocidade simuladas

A massa simulada processada no lote representa a carga acumulada no prato.
O modelo didático usa:

```
força_N = (pesoProcessadoGramas / 1000) * SERVO_SIMULATED_FORCE_PER_KG_N
velocidade_m_s = CONVEYOR_ESTIMATED_SPEED_M_S / (1 + força_N / CONVEYOR_SIMULATED_FORCE_REFERENCE_N)
```

Com os valores iniciais, 0 g produzem 0 N e 0,10 m/s; 500 g produzem 1 N e
aproximadamente 0,067 m/s; 1000 g produzem 2 N e 0,05 m/s. A velocidade é zero
quando a placa informa parada e fica desconhecida sem telemetria recente.
Sem lote configurado, a carga simulada é zero; iniciar outro lote reinicia
essa carga. A simulação é determinística, sem saltos aleatórios a cada consulta.

O painel indica **Simulada** e mostra a força equivalente em N. Não há sensor
de força ou velocidade, nem relação mecânica medida entre servo e motor da
esteira. Essa associação existe somente no modelo; ela não regula o motor
físico. Os dois coeficientes e a velocidade de referência ficam em `config.py`.

Ao detectar a desconexão do WebSocket, o firmware para a esteira. Se houver
um ciclo em andamento, conclui o posicionamento mas só retoma o transporte
quando a conexão for restabelecida. Comandos com ângulo/tempo inválido são
rejeitados com motivo no Monitor Serial, sem travar a esteira nem interromper
um ciclo válido em andamento. Quando conectada e livre, a placa mantém a
esteira ligada, mesmo sem detecções.

### Tempo de transporte e espaçamento dos objetos

A captura drena continuamente o vídeo em uma thread, enquanto outra rotina
analisa o quadro mais recente. Só um quadro fica pendente, sendo substituído
quando chega outro; não existe fila de imagens nem de materiais. Um quadro
que passou mais de `CAMERA_MAX_PENDING_FRAME_AGE_SECONDS` (padrão 0,5 s)
aguardando processamento local é descartado. Esse limite não mede o atraso
interno do celular ou da rede. O comando é criado antes de desenhar o vídeo.
O WebSocket consulta comandos a cada `SORT_POLL_INTERVAL_SECONDS` (0,01 s).

O comando é criado após `SORT_CONFIRM_FRAMES` quadros consecutivos (padrão 3).
Ao receber o comando, a ESP32:

1. Para o motor da esteira.
2. Aguarda `SORT_STOP_MS` (padrão 200 ms), para acomodar a parada mecânica.
3. Aplica ao servo o ângulo do recipiente correspondente.
4. Aguarda `SORT_SETTLE_MS` (atualmente 1500 ms), para posicionamento.
5. Religa a esteira e responde `done`, com `conveyor_running: true`.

O recipiente permanece nessa posição até a próxima peça. Não há espera
adicional para a queda nem fila. As etapas usam `millis()`, sem bloquear a
comunicação com `delay()` durante o ciclo.

Calibre os tempos de parada e posicionamento em `config.py`. Eles são
estimativas; sem sensores não confirmam parada total ou alinhamento físico.
A câmera deve identificar a peça antes de ela alcançar a saída. Deixe
`SORT_ACK_TIMEOUT_SECONDS` maior que a soma dos tempos.

Posicione a ROI antes da saída da esteira, deixando distância suficiente para
a confirmação nos quadros, a transmissão e a parada física. A espera de
200 ms ocorre depois do comando de parada e antes de aplicar o pulso no servo.
Os 1500 ms seguintes são para o movimento; não atrasam o envio desse pulso.
As mensagens da placa incluem `millis()` para comparar esses dois momentos.
O firmware verifica se a inicialização do PWM foi bem-sucedida e informa
`PWM ativo` ou `PWM FALHOU` no boot. Isso não confirma movimento físico.

### Teste isolado dos dois SG90

Se o servo não mover, gere as configurações com
`python generate_esp32_config.py` e abra `TesteServo/TesteServo.ino` na Arduino
IDE. Esse sketch usa os mesmos pinos, frequência e pulsos do `config.py` e
mantém as entradas da esteira em LOW. Não usa câmera nem Wi-Fi.

Com o curso combinado de 360°, alterna o prato entre 90°, 180° e 270°:
cada servo passa por 45°, 90° e 135°, respectivamente. A troca acontece a cada
`SERVO_TEST_STEP_MS` (2000 ms). Teste sem o prato/carga e acompanhe o Monitor
Serial em 115200 baud. As mensagens indicam os pulsos aplicados. Se o PWM
inicializar mas o servo não se mover nesse teste, investigue fiação,
alimentação, carga ou o próprio servo. Regrave `EcoCycleClient.ino` para
retornar à operação normal.

Peças da mesma cor usam o mesmo ângulo; se o recipiente já está alinhado,
não haverá novo deslocamento do servo.

**Mantenha as peças espaçadas.** A peça anterior precisa cair no recipiente
antes que outra peça provoque uma troca de recipiente. A retomada mantém o
mesmo ID bloqueado para não parar repetidamente pelo objeto já tratado.
Durante um ciclo ou sem conexão, não são criados novos comandos. Depois,
outra peça ainda visível pode ser confirmada nos novos quadros. Se passar
pela câmera durante a indisponibilidade, não será recuperada por uma fila.

A placa tenta restabelecer o WebSocket a cada 5 segundos após desconectar.
O firmware envia sua identificação automaticamente. Somente uma ESP32 pode usar
`/ws/sorter` por vez; monitoramento continua disponível em `/ws/detections`.

## Protocolo de comandos

Ao conectar, a placa envia
`{"type":"client_hello","protocol":3,"servo_count":2,"operator_start":true}`. O servidor
aguarda essa identificação antes de enviar qualquer `hello`; firmware antigo
recebe erro e não recebe autorização para operar o mecanismo de dois eixos.
Regrave a ESP32 com o sketch atualizado.

O servidor responde com
`{"type":"hello","session_id":"...","thermal_blocked":false,"triage_enabled":false}`.
O clique em iniciar envia
`{"type":"triage_control","session_id":"...","enabled":true}`; pausa e
conclusão enviam o mesmo tipo com `enabled:false`. A placa confirma o estado
em `conveyor_state` e `ack`, incluindo `triage_enabled`. A autorização é
verificada na partida, nas retomadas e antes de aceitar um novo ciclo.

Para cada novo ID confirmado durante uma triagem autorizada, envia:

```json
{
  "type": "sort_cycle",
  "session_id": "sessao-do-servidor",
  "command_id": "identificador-unico",
  "track_id": 1,
  "color": "Laranja",
  "container": "A",
  "material": "Plástico",
  "angle_deg": 0,
  "stop_ms": 200,
  "settle_ms": 800
}
```

A ESP32 responde depois do intervalo completo:

```json
{"type":"ack","session_id":"sessao-do-servidor","command_id":"identificador-unico","status":"done","conveyor_running":true}
```

O servidor aguarda essa confirmação para aceitar um novo ciclo.
Se o servo/esteira estiver desabilitado ou o comando for inválido, a resposta usa
`status: "error"` e o servidor registra a falha. `done` confirma apenas que
o ciclo de parar, aplicar o pulso e retomar foi executado: sem sensor externo,
não comprova o alinhamento físico nem que o objeto caiu.

Reaparições do mesmo ID não geram novas instruções. Se a conexão cair, o
mesmo comando do ciclo atual pode ser retransmitido dentro do prazo de confirmação;
o firmware reconhece o comando
em andamento ou o último concluído sem repetir o movimento. Essa memória
é perdida se a ESP32 reiniciar. O servo é posicional, portanto os comandos
sempre expressam um destino absoluto, não um incremento de giro.

Comandos rejeitados, ciclos sem confirmação e objetos ignorados são registrados
no terminal. O único comando mantido é o do ciclo atual. Se não houver resposta
em `SORT_ACK_TIMEOUT_SECONDS`, o ciclo é cancelado e a conexão é encerrada.
Após reiniciar o servidor os IDs/sessão mudam;
um objeto ainda visível pode gerar novo comando. O rastreamento original
também pode criar um ID novo após oclusão/perda do objeto.

## Monitoramento das detecções

### Quadros JPEG incompletos

O leitor MJPEG separa os quadros respeitando os segmentos JPEG. Quando chega
outro início de imagem antes do fim da anterior, descarta a anterior e retoma
a leitura no novo quadro. Miniaturas dentro de metadados não são tratadas
como novos quadros. O limite fica em `CAMERA_MAX_FRAME_BYTES`.
Se nenhum quadro decodificável chegar por `CAMERA_VALID_FRAME_TIMEOUT`, o
servidor tenta reconectar. Erros de decodificação não interrompem a leitura
do próximo quadro. Os avisos nativos do codec não foram ocultados: um JPEG
com dados comprimidos danificados ainda pode gerar avisos mesmo com seus
marcadores completos. Esta correção não repara dados já corrompidos na origem.

### Dashboard

Abaixo das detecções, o painel mostra três cartões: temperatura simulada,
velocidade estimada e porcentagem do peso processado do lote. Embaixo ficam
os pesos de plástico, alumínio, metal e rejeito no lote atual.

Sem sensor de velocidade, `CONVEYOR_ESTIMATED_SPEED_M_S` define somente a
referência exibida quando a ESP32 informa motor ligado (padrão 0,10 m/s).
Parada conhecida mostra 0,00 m/s; sem telemetria mostra “—”. Esse valor não
é uma medição nem altera o acionamento do motor. O JSON inclui `conveyor`
com `speed_m_s`, `speed_estimated`, `running` e `state_known`.
Sem lote cadastrado, a porcentagem e os pesos mostram “—”.

### Temperatura simulada

O painel e o JSON de `/api/detections` e `/ws/detections` incluem `temperature`:

```json
{"simulated":true,"temperature_c":28.0,"ambient_c":25.0,"conveyor_running":true,"continuous_run_seconds":20.0,"state_known":true}
```

É um dado fictício calculado no servidor, não uma leitura de sensor:

- Começa em `TEMP_AMBIENT_C` (25 °C).
- Aumenta `TEMP_HEATING_C_PER_SECOND` (0,15 °C/s) enquanto ligada,
  limitado a `TEMP_MAX_C` (70 °C).
- Diminui `TEMP_COOLING_C_PER_SECOND` (0,10 °C/s) quando parada,
  sem cair abaixo da temperatura ambiente. Não volta à temperatura ambiente
  instantaneamente ao parar: conserva o calor acumulado.
- O contador de tempo consecutivo zera ao parar e recomeça ao ligar novamente.
- O cálculo usa tempo decorrido, independentemente do navegador estar aberto
  ou de quantas vezes a API é consultada. Reiniciar o Python reinicia a simulação.

O firmware atualizado envia `{"type":"conveyor_state","session_id":"...","running":true}`
ao ligar/parar e periodicamente a cada `ESP32_TELEMETRY_INTERVAL_MS` (1000 ms).
O servidor recebe essas mensagens mesmo quando não há objeto sendo separado.
O estado representa o sinal de acionamento da ESP32, sem sensor de rotação.
Se desconectar ou não houver atualização por `TEMP_STATE_TIMEOUT_SECONDS`
(3 s), a simulação assume parada e esfria, com `state_known: false` no painel.
Para aquecer com a esteira ligada, é necessário regravar o firmware com
essa telemetria; apenas abrir o site não faz a temperatura subir.

### Dados dos objetos

Cada mensagem é um JSON em texto, enviado imediatamente ao conectar e,
depois, a cada 500 ms. Esse intervalo pode ser alterado em
`config.py`, na variável `WS_SEND_INTERVAL`.

```json
{
  "connected": true,
  "count": 1,
  "counts": {"Laranja": 1, "Verde-claro": 0, "Azul-claro": 0, "Roxo": 0},
  "detections": [
    {"id": 1, "color": "Laranja", "x": 120, "y": 150, "w": 40, "h": 40,
     "area": 1521, "material": "Plástico", "container": "A"}
  ]
}
```

- `connected`: indica que o servidor já recebeu uma imagem da câmera.
  Mantém a semântica da API HTTP atual: se a câmera cair depois, o último
  quadro e as últimas detecções podem continuar disponíveis. Não representa
  uma verificação contínua da conexão da câmera.
- `count` e `counts`: quantidade atual total e por cor.
- `detections`: objetos, IDs e caixas em pixels na imagem processada de 640 × 480.
- `material` e `container`: associação de cor, material e recipiente.

As mensagens são retratos do estado, não eventos de entrada de objetos.
O mesmo objeto aparece em várias mensagens com o mesmo ID; ao usar motores
ou atuadores, considere isso para não executar uma ação a cada atualização.
Os IDs são temporários e reiniciam quando o servidor é reiniciado.
O WebSocket transmite os dados de detecção; o vídeo continua na rota `/video`.

## Organização

- `app.py`: servidor HTTP e função que fornece os dados às duas conexões.
- `websocket_server.py`: rota WebSocket e envio periódico.
- `sorting.py`: confirmação de novos IDs e controle de um único ciclo por vez.
- `vision.py`: captura e visão computacional, com envio de cada frame processado à separação.
- `config.py`: todas as opções de instalação, câmera, detecção, servidor, ESP32 e servo.
- `temperature.py`: simulação de temperatura e tempo consecutivo de acionamento.
- `generate_esp32_config.py`: exporta as opções da placa em C++.
- `esp32/EcoCycleClient/EcoCycleConfig.h`: configuração gerada; não editar manualmente.

Referências: [Flask-Sock](https://flask-sock.readthedocs.io/en/latest/quickstart.html),
[WebSockets para Arduino](https://github.com/Links2004/arduinoWebSockets),
[ArduinoJson 7](https://arduinojson.org/v7/tutorial/deserialization/).
Controle de pulsos: [API da ESP32Servo](https://github.com/madhephaestus/ESP32Servo/blob/master/src/ESP32Servo.h).

## Testes sem hardware

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Os testes verificam o servidor, não validam o PWM, o giro físico ou os tempos
da esteira. O sketch precisa ser compilado e carregado para o modelo de ESP32
escolhido na Arduino IDE.
