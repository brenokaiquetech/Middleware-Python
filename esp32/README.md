# ESP32: separar objetos por cor com servo posicional

O computador interpreta a câmera e a ESP32 controla a esteira e o prato.
O ciclo é **identificar → parar a esteira → posicionar o recipiente →
retomar a esteira até identificar outra peça**. O controle
implementado é para **servo posicional**, com curso em `SERVO_TRAVEL_DEG`, não para
servo de rotação contínua. Os materiais abaixo são uma associação configurada
por cor; não são identificados fisicamente pela câmera.

| Cor detectada | Recipiente | Material atribuído | Ângulo inicial |
|---|---|---|---|
| Laranja | A | Plástico | 0° |
| Verde-claro | B | Alumínio | 60° |
| Azul-claro | C | Metal | 120° |
| Roxo | D | Rejeito | 180° |

Esses ângulos representam posições do eixo que devem alinhar o recipiente
com a queda da esteira. A imagem não determina o zero nem o sentido do servo:
calibre `SORT_TARGETS` em `config.py` na montagem real. Verde e azul continuam
usando as mesmas faixas HSV anteriores (`Verde-claro` e `Azul-claro`).
O servo atual foi confirmado como 180°: os quatro destinos estão distribuídos
nesse curso como referência inicial. Ajuste os ângulos à posição real dos
recipientes. Um prato que exija uma volta inteira precisa de uma montagem
mecânica compatível; o software não aumenta o curso físico do servo.

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
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

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

- `SERVO_PIN`: saída de sinal, inicialmente GPIO 18. Confira sua placa.
- `SERVO_MIN_US`, `SERVO_MAX_US`, `SERVO_FREQUENCY_HZ`: consulte o datasheet
  do modelo e calibre. **500–2500 µs e 50 Hz são valores de exemplo**, não uma
  especificação confirmada do seu servo.
- `SERVO_TRAVEL_DEG`: atualmente 180°, conforme o servo confirmado.
  A geração da configuração rejeita destinos fora desse curso.
- `SERVO_CALIBRATED`: inicia em `False`; o firmware recebe os comandos mas
  responde `error` e não conecta o PWM. Configure os limites reais e então
  mude para `True`, gere o arquivo e regrave a placa para habilitar o acionamento.

A conversão de ângulo para pulso é linear. O firmware usa
`writeMicroseconds()`: a função `write()` da ESP32Servo limita ângulos a 180°.
Não use este firmware em um servo contínuo, no qual pulsos controlam velocidade.

Ligue o sinal ao GPIO configurado, o servo a uma fonte compatível com seu
modelo e una o GND da fonte ao GND da ESP32. A ligação de potência do servo
não passa pelo GPIO.

### Motor da esteira e L9110S

O firmware controla um canal do L9110S, com o motor TT ligado às saídas desse
canal. Os valores iniciais no `config.py` são:

| Conexão | Configuração | Valor inicial |
|---|---|---|
| Entrada IA do canal do driver | `CONVEYOR_PIN_IA` | GPIO 26 |
| Entrada IB do mesmo canal | `CONVEYOR_PIN_IB` | GPIO 25 |
| Sinal do servo | `SERVO_PIN` | GPIO 18 |
| Sentido do transporte | `CONVEYOR_FORWARD_IA_HIGH` | `True` |

Confirme os GPIOs disponíveis no seu modelo de ESP32 e adapte à fiação real.
Os três pinos devem ser diferentes. Motor TT é ligado ao driver; não ao GPIO.
Una o GND da ESP32 ao GND do driver e use alimentação compatível com o motor.
**IB não pode ficar flutuando.** As duas entradas precisam estar ligadas aos
GPIOs atuais do `config.py`, no mesmo canal do L9110S. Alterar o código não
substitui essa ligação.

Habilite `CONVEYOR_ENABLED = True` depois de conferir as ligações. Para iniciar
o transporte, `SERVO_CALIBRATED` também precisa estar em `True`. O firmware
deixa a esteira parada durante o boot e a conexão Wi-Fi, iniciando depois do
`hello` do servidor. A direção usa IA alto/IB baixo ou o inverso; a parada usa
as duas entradas baixas, conforme a [tabela do módulo L9110S](https://docs.sunfounder.com/projects/3in1-kit-r4/en/latest/components/component_l9110s.html).
Esta versão liga/desliga o motor; não regula a velocidade por PWM.

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

### Teste isolado do SG90

Se o servo não mover, gere as configurações com
`python generate_esp32_config.py` e abra `TesteServo/TesteServo.ino` na Arduino
IDE. Esse sketch usa os mesmos pinos, frequência e pulsos do `config.py` e
mantém as entradas da esteira em LOW. Não usa câmera nem Wi-Fi.

Com o curso atual de 180°, alterna 90°, 60° e 120° a cada
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
Não é necessário enviar comando de inscrição. Somente uma ESP32 pode usar
`/ws/sorter` por vez; monitoramento continua disponível em `/ws/detections`.

## Protocolo de comandos

Ao conectar, o servidor envia `{"type":"hello","session_id":"..."}`.
Para cada novo ID confirmado, envia uma instrução:

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
