# Teste do ciclo da ESP32 no computador

`test_cycle.cpp` inclui o sketch real de produção. Os arquivos em `fakes/`
substituem apenas o relógio, os GPIOs, o Wi-Fi, o WebSocket e o servo.
A leitura e a escrita de JSON usam a biblioteca ArduinoJson 7 real.
Nenhum motor ou dispositivo de rede é acionado.

Com um compilador C++17 e a biblioteca ArduinoJson disponível, na raiz do
projeto execute (substitua o caminho da biblioteca):

```sh
g++ -std=c++17 -Itests/firmware/fakes -I/caminho/ArduinoJson/src tests/firmware/test_cycle.cpp -o /tmp/ecocycle-cycle-test
/tmp/ecocycle-cycle-test
```

No Windows também pode ser compilado com MSVC em um terminal de desenvolvedor
com Windows SDK instalado. Use `/std:c++17 /EHsc` e os mesmos diretórios de
include. O header `EcoCycleConfig.h` deve estar atualizado e com os dois
acionamentos habilitados para esses cenários.

Os cenários verificam partida sem detecções, parada antes de mover o servo,
espera de posicionamento, retomada sem outra peça, comandos duplicados ou
rejeitados, desconexão/reconexão e o estouro do contador `millis()`.
O posicionamento usa dois SG90: o destino total de 360° exige ambos em 180°;
180° no prato exige ambos em 90°. Também há cenários para calibração/inversão
do pulso e falha de inicialização de apenas um dos dois canais PWM.
