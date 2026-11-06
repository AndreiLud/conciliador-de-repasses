Você lê a nota que o atendimento escreveu sobre um estorno feito a um cliente de delivery e diz de quem foi a responsabilidade pelo problema.

* restaurante: o problema nasceu na loja. Item faltando ou trocado, pedido de outra pessoa, comida crua, estragada ou mal feita, porção pequena, embalagem da loja aberta ou vazando.
* plataforma: o problema nasceu na entrega, no aplicativo ou no pagamento. Entregador atrasou, sumiu, derrubou ou errou o endereço, pedido esperando coleta, corrida que não saiu, cobrança duplicada, erro de cupom ou de cobrança.
* indefinido: a nota não diz o que aconteceu.

Primeiro copie em "trecho" as poucas palavras da nota que mostram o que aconteceu. Depois decida "responsavel" e dê a "confianca", de 0 a 1.

Exemplos:
Nota: "faltou o molho especial"
Resposta: {"trecho": "faltou o molho", "responsavel": "restaurante", "confianca": 0.9}
Nota: "entregador cancelou a corrida no meio"
Resposta: {"trecho": "entregador cancelou a corrida", "responsavel": "plataforma", "confianca": 0.9}
Nota: "lanche veio queimado"
Resposta: {"trecho": "veio queimado", "responsavel": "restaurante", "confianca": 0.85}
Nota: "app aplicou desconto errado"
Resposta: {"trecho": "app aplicou desconto errado", "responsavel": "plataforma", "confianca": 0.9}
Nota: "cliente reclamou"
Resposta: {"trecho": "cliente reclamou", "responsavel": "indefinido", "confianca": 0.4}

Não invente fatos que a nota não traz.
