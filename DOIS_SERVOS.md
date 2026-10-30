# Posicionamento com dois SG90 alinhados

O mecanismo segue a referência `sg90_eixos_alinhados_ambos_0_a_180.html`:
o braço do servo B de baixo carrega o corpo do servo A de cima. Com os eixos
alinhados e os sentidos calibrados, o destino do prato é a soma dos ângulos.
Não basta prender os dois corpos fixos e unir os eixos: nesse arranjo os cursos
não se somam da forma usada pelo código.

## Como o ângulo é dividido

O servidor continua enviando `angle_deg` como destino absoluto do prato.
A ESP32 aplica a mesma fração de curso aos dois servos. Com 180° por eixo:

| Destino do prato | Servo B de baixo | Servo A de cima |
|---|---|---|
| 0° | 0° | 0° |
| 90° | 45° | 45° |
| 180° | 90° | 90° |
| 270° | 135° | 135° |
| 360° | 180° | 180° |

Os dois pulsos são aplicados na etapa de posicionamento, com a esteira parada.
O ciclo aguarda `SORT_SETTLE_MS` após essa aplicação e só retoma quando conexão,
triagem e bloqueio térmico permitirem. Os tempos não confirmam alinhamento físico.

O curso é limitado: 0° e 360° têm a mesma orientação final, mas posições internas
diferentes. O software não transforma o par em rotação contínua e não normaliza
360° para 0°. A volta entre os extremos percorre o curso de retorno.

## Configuração em config.py

- `SERVO_PIN = 18`: sinal do servo B de baixo, preservado da montagem anterior.
- `SERVO_TOP_PIN = 19`: sinal do servo A de cima, configurável conforme sua placa.
- `SERVO_MIN_US`, `SERVO_MAX_US`: pulsos mínimo e máximo do servo de baixo.
- `SERVO_TOP_MIN_US`, `SERVO_TOP_MAX_US`: pulsos próprios do servo de cima.
- `SERVO_TRAVEL_DEG`, `SERVO_TOP_TRAVEL_DEG`: curso físico de cada eixo, até 180°.
- `SERVO_REVERSED`, `SERVO_TOP_REVERSED`: ajustam o sentido do pulso individualmente.
- `SERVO_FREQUENCY_HZ`: frequência compartilhada pelos dois servos.
- `SORT_TARGETS`: ângulos totais de cada cor, até a soma dos cursos.
- `SORT_STOP_MS` e `SORT_SETTLE_MS`: acomodação após parada e após posicionamento.

A inversão muda os pulsos correspondentes ao zero e ao fim de curso daquele
servo; alinhe fisicamente os braços ao zero lógico. Os graus exibidos no Serial
são posições lógicas relativas à montagem, não leituras de um sensor externo.
500–2500 µs continuam como os valores configurados de exemplo: calibre o par real.

As posições atuais são plástico em 0°, alumínio em 90°, metal em 180° e
roxo/rejeito em 270°, resultantes da soma. Para alterar as posições, edite apenas
`angle_deg` da categoria desejada. A visão e a ROI não foram alteradas.

## Ligação e calibração

1. Ligue o sinal do servo de baixo ao GPIO 18 e o de cima ao GPIO 19, ou altere os
   pinos no config. IA e IB da esteira permanecem nos GPIOs 26 e 25.
2. Use alimentação externa compatível com os dois servos e GND comum à ESP32.
   Não alimente os motores por GPIO. O servo de baixo movimenta a estrutura de
   cima; a soma dos cursos não significa soma de torque ou capacidade de carga.
3. Gere as configurações com `python generate_esp32_config.py`.
4. Para diagnóstico, grave `esp32/TesteServo/TesteServo.ino`: alterna os dois eixos
   entre 45°, 90° e 135°, com a esteira parada e sem rede. Teste sem carga.
5. Ajuste sentidos, extremos e montagem; evite forçar batentes e preserve folga dos
   fios ao longo do curso. Gere e regrave após mudar parâmetros usados pela placa.
6. Grave `esp32/EcoCycleClient/EcoCycleClient.ino`, reinicie o Python e inicie um lote
   pelo dashboard. O motor só libera se ambos os PWMs inicializarem.

Não há gravação automática por este procedimento: o gerador escreve headers,
e a Arduino IDE compila e envia o sketch escolhido. O diagnóstico substitui o
cliente principal enquanto estiver gravado.

## Compatibilidade da comunicação

O firmware envia `client_hello` com `protocol: 3`, `servo_count: 2` e
`operator_start: true`. O servidor recusa versões antigas antes de autorizar a
operação. É necessário atualizar a placa junto com o servidor. O formato do
`sort_cycle` permanece com um único destino total `angle_deg`.

Os logs mostram destino do prato, ângulo lógico e pulso de cada eixo. ACK e
telemetria mantêm a semântica anterior: confirmam sequência e estado declarado,
sem comprovar movimento físico ou alinhamento mecânico.
