# Simulação de pesos por lote

Implementa as regras do documento Lógica_Peso_Materiais.pdf em Python.
Não existe balança nem integração com backend externo nesta etapa.
Os valores são fictícios e calculados em **gramas inteiras**.

| Cor | Material exibido | Categoria do documento | Faixa normal |
|---|---|---|---|
| Laranja | Plástico | `PLASTICO` | 100–300 g |
| Verde-claro | Alumínio | `OUTRO_METAL` | 200–600 g |
| Azul-claro | Metal | `METAL` | 300–700 g |
| Roxo | Rejeito | `REJEITO` | 50–250 g |

As faixas ficam em `BATCH_WEIGHT_RANGES_G` no `config.py`. A associação de
cores e categorias fica em `BATCH_MATERIAL_BY_COLOR`; alumínio foi associado
a `OUTRO_METAL` para manter as quatro categorias do documento.

## Regras

1. Cadastre o identificador e o peso total previsto antes de contabilizar peças.
2. Cada novo ID de câmera é confirmado em `SORT_CONFIRM_FRAMES` quadros
   consecutivos, mantendo a lógica de visão e ROI existente.
3. O peso é sorteado entre o mínimo da categoria e o menor valor entre
   o máximo da categoria e o saldo disponível, incluindo ambos os limites.
4. Se o saldo for menor que o mínimo, a última peça recebe exatamente o saldo,
   com `tipoCalculo: "AJUSTE_SALDO"`. Nos demais casos, usa `"ALEATORIO"`.
5. Atualizam-se o peso processado, o subtotal e a quantidade daquela categoria.
6. O lote é `CONCLUIDO` ao atingir exatamente o total. Não aceita novas peças.

A soma nunca ultrapassa o peso total. Não são gerados pesos continuamente:
cada peça recebe um peso uma única vez. Atualizar a tela ou repetir o mesmo
`eventoId` não sorteia outro peso nem modifica totais. Não há meta de peso
por categoria: a composição depende dos materiais realmente identificados.

A contabilização da câmera acontece na identificação confirmada, como no
documento, independentemente da conexão da ESP32 e da confirmação do motor.
Não comprova que a peça caiu no recipiente. A conclusão deste lote simulado
não modifica o acionamento da esteira/servo: esse controle mantém seu ciclo
de parar, posicionar e retomar. Não foi adicionada fila de objetos.

## Iniciar um lote localmente

Com o servidor em execução, use outro terminal PowerShell:

```powershell
Invoke-RestMethod -Method Post -Uri 'http://localhost:8000/api/lote' -ContentType 'application/json' -Body '{"loteId":"LOTE-001","pesoTotalLoteGramas":1000}'
```

A câmera passa a contabilizar os IDs confirmados e o painel exibe o saldo e
os subtotais. Até o lote ser cadastrado, não são sorteados pesos.
Use a porta configurada em `PORT` caso tenha alterado a porta padrão.

Também é possível testar sem câmera e sem ESP32:

```powershell
Invoke-RestMethod -Method Post -Uri 'http://localhost:8000/api/lote/pecas' -ContentType 'application/json' -Body '{"eventoId":"EVT-001","material":"PLASTICO"}'
Invoke-RestMethod -Method Get -Uri 'http://localhost:8000/api/lote'
```

O endpoint de peças é apenas uma entrada de simulação; não aciona motores.
Não envie o mesmo objeto manualmente e pela câmera com IDs diferentes, pois
isso representa dois eventos distintos. Posteriormente, a integração com o
backend deverá definir a origem e os identificadores dos eventos.

## API local

- `POST /api/lote`: recebe `loteId` (texto não vazio) e
  `pesoTotalLoteGramas` (inteiro positivo, até 2^53−1).
- `GET /api/lote`: resumo do lote atual.
- `POST /api/lote/pecas`: recebe `eventoId` (texto) e `material`
  (`PLASTICO`, `METAL`, `OUTRO_METAL` ou `REJEITO`).
- `/api/detections` e `/ws/detections`: incluem o resumo na propriedade `batch`.

Resumo de exemplo:

```json
{
  "simulado": true,
  "loteId": "LOTE-001",
  "pesoTotalLoteGramas": 1000,
  "pesoProcessadoGramas": 1000,
  "saldoLoteGramas": 0,
  "totaisPorMaterial": {"PLASTICO": 380, "METAL": 620, "OUTRO_METAL": 0, "REJEITO": 0},
  "quantidades": {"PLASTICO": 2, "METAL": 1, "OUTRO_METAL": 0, "REJEITO": 0},
  "statusLote": "CONCLUIDO",
  "ultimaPeca": {
    "loteId": "LOTE-001", "eventoId": "EVT-003", "material": "PLASTICO",
    "pesoSimuladoGramas": 80, "tipoCalculo": "AJUSTE_SALDO"
  }
}
```

A API também informa `nomesMateriais` com os rótulos para exibição.
Uma peça aceita retorna `sucesso: true` e o resumo atualizado. Eventos
duplicados retornam `EVENTO_DUPLICADO`; lotes encerrados, `LOTE_ENCERRADO`;
sem lote, `LOTE_NAO_CONFIGURADO`. Esses resultados usam HTTP 409; dados
inválidos usam HTTP 400.

Repetir o cadastro do mesmo lote e peso mantém o progresso. Alterar o peso
de um lote já cadastrado ou substituir um lote incompleto retorna HTTP 409.
Um lote novo só é iniciado após a conclusão do anterior, usando outro ID.
Os IDs já pesados pela câmera não voltam a ser usados em outro lote.

Os dados ficam na memória: reiniciar o Python reinicia a simulação e os
identificadores de câmera. Não há banco de dados nem histórico de lotes
finalizados; essa persistência poderá ser definida na integração posterior.

## Testes

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Os testes usam geradores controlados e verificam o exemplo de saldo final
de 80 g, as faixas, duplicatas, limites, concorrência e as rotas HTTP.
