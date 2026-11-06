# Avaliação

Saída de `python run_all.py`, medida contra o gabarito em `data/answer_key/`. Os números do site e dos READMEs saem do mesmo cálculo (`docs/data/facts.json`).

## Definições

* **Detectado:** existe uma divergência sinalizada (confirmada ou na fila de revisão) com a mesma chave do erro plantado (pedido, estorno, repasse ou restaurante e semana).
* **Achado automático:** a divergência foi confirmada sem revisão humana e com o tipo certo.
* **Precisão automática:** entre as divergências confirmadas, quantas correspondem a um erro plantado do mesmo tipo.
* **Falso positivo:** uma armadilha (algo que parece erro, mas está certo) que virou divergência confirmada. Armadilhas que caem na fila de revisão custam tempo de analista, mas não geram carta errada.

## Resultado geral

| Métrica | Só regras | Regras e IA |
|---|---|---|
| Erros plantados | 150 | 150 |
| Detectados (revocação da detecção) | 100,0% | 100,0% |
| Achados automáticos com o tipo certo | 145 (96,7%) | 145 (96,7%) |
| Precisão automática | 95,4% | 100,0% |
| Falsos positivos nas armadilhas | 7 de 1.908 | 0 de 1.908 |
| Casos na fila de revisão | 28 | 18 |

## Por tipo de erro

| Tipo | Casos | Achados com o tipo certo | Precisão | Revocação | Plantado: restaurante recebeu a mais | Plantado: restaurante recebeu a menos |
|---|---|---|---|---|---|---|
| Comissão com taxa errada | 25 | 25 | 100,0% | 100,0% | R$ 10,62 | R$ 43,87 |
| Plano antigo aplicado depois da troca | 8 | 8 | 100,0% | 100,0% | R$ 3.812,68 | R$ 1.231,94 |
| Taxa de pagamento errada | 25 | 25 | 100,0% | 100,0% | R$ 8,99 | R$ 32,82 |
| Cupom da plataforma cobrado do restaurante | 20 | 20 | 100,0% | 100,0% | R$ 0,00 | R$ 193,68 |
| Estorno não descontado | 15 | 10 | 100,0% | 66,7% | R$ 590,90 | R$ 0,00 |
| Estorno descontado duas vezes | 10 | 10 | 100,0% | 100,0% | R$ 0,00 | R$ 435,90 |
| Pedido pago em duplicidade | 15 | 15 | 100,0% | 100,0% | R$ 656,38 | R$ 0,00 |
| Pedido entregue fora do repasse | 20 | 20 | 100,0% | 100,0% | R$ 0,00 | R$ 1.128,61 |
| Valor transferido diferente do extrato | 8 | 8 | 100,0% | 100,0% | R$ 5.518,00 | R$ 313,29 |
| Repasse pago em duplicidade | 4 | 4 | 100,0% | 100,0% | R$ 9.648,04 | R$ 0,00 |

## Armadilhas

| Armadilha | Casos | Falso positivo | Na fila de revisão |
|---|---|---|---|
| Cancelado antes do preparo, sem cobrança | 1.060 | 0 | 0 |
| Pedido de domingo à noite concluído depois da meia-noite | 384 | 0 | 0 |
| Estorno assumido pela plataforma | 244 | 0 | 13 |
| Pedido concluído depois do fechamento do período | 95 | 0 | 0 |
| Diferença de centavos dentro da tolerância | 80 | 0 | 0 |
| Ajuste manual com chamado e justificativa | 30 | 0 | 0 |
| Segundo estorno legítimo do mesmo pedido | 10 | 0 | 0 |
| Pix devolvido e reenviado | 5 | 0 | 0 |

## Casos ambíguos: o que a IA acrescenta

Casos ambíguos são os que a regra não fecha sozinha. Três políticas, medidas nos mesmos casos:

* **Regra:** palavras-chave na nota do atendimento (estornos) ou a primeira hipótese que confere, por prioridade fixa (linhas do extrato legado).
* **IA sozinha:** o modelo local decide; confiança abaixo do limite vai para revisão. Já inclui as guardas do código (tipo dentro das opções, hipótese que confere, trecho que existe na nota) e uma nova tentativa quando a resposta é reprovada.
* **Juntas (política final):** a IA decide e precisa citar o trecho que decide; se a regra tem resposta e discorda, o caso vai para revisão.

Cada célula mostra certos, errados e enviados para revisão.

| Grupo | Casos | Regra | IA sozinha | Juntas |
|---|---|---|---|---|
| Estorno sem responsável (só a nota do atendimento) | 63 | 28, 7, 28 | 48, 0, 15 | 45, 0, 18 |
| Linha do extrato legado com mais de uma causa possível | 5 | 5, 0, 0 | 1, 3, 1 | 5, 0, 0 |
| **Total** | 68 | 33, 7, 28 | 49, 3, 16 | 50, 0, 18 |

Leitura honesta: nas linhas do extrato legado a regra acertou todos os casos e a IA errou a maioria, então ali a regra decide e a IA roda só em modo sombra, para esta medição (`LINES_AI=1` devolve a decisão a ela). O ganho está nos estornos sem responsável, em que a única evidência é texto livre.

## Revisão humana das cartas escritas pela IA

Lemos uma amostra fixa de 20 cartas escritas pelo modelo local, cada uma contra os fatos que ele recebeu. Resultado: 5 corretas, 3 confusas e 12 com fato errado ou inventado (por exemplo, prometer que o valor já foi ajustado, inverter quem recebeu a mais ou contar pedidos a mais). As checagens automáticas de número e de estilo aprovavam essas cartas, porque o erro é de sentido e não de número.

Decisão: as cartas publicadas usam o texto montado pelo código, que é exato. A escrita pela IA continua no código e pode ser ligada com `LETTERS_AI=1` para testar um modelo maior. Cada carta avaliada está em `project_docs/revisao_cartas_ia.csv`.

## Cartas e resumos

* Cartas geradas: 134, com texto do código. Cartas com texto da IA nesta execução: 0.
* Cartas finais com problema de estilo: 0. Com número fora dos dados: 0.
* Resumos semanais: 5, com texto do código. A leitura da semana pela IA também foi testada e desligada: mesmo sem números, o modelo apontava como maior valor um tipo que não era.
* A amostra de cartas finais para revisão humana está em `project_docs/cartas_amostra/`.

## Uso do modelo local

* Provedor: llamacpp. Modelo: qwen3.5-2b-q4_k_m. Custo de API: zero.
* Chamadas: 69 (69 respondidas pelo cache nesta execução).
* Tokens de entrada: 34.694. Tokens de saída: 3.112.
* Tempo de máquina gasto quando as respostas foram geradas: 1.896,3 segundos, em CPU sem placa de vídeo. Repetir pelo cache leva segundos.

## Valor das divergências

* Restaurantes receberam a mais: R$ 20.245,61 plantados, R$ 20.012,31 achados automaticamente.
* Restaurantes receberam a menos: R$ 3.380,11 plantados, R$ 3.380,11 achados automaticamente.

## Horas economizadas (estimativa)

Estimativa, não medição. As premissas estão abaixo e podem ser editadas na calculadora do site.

| Premissa | Valor |
|---|---|
| Restaurantes conferidos por semana | 200 |
| Minutos para conferir um repasse na planilha | 6 |
| Minutos para investigar uma divergência na planilha | 20 |
| Minutos para escrever uma carta ao restaurante | 15 |
| Minutos para conferir uma divergência já explicada pela ferramenta | 3 |
| Minutos para resolver um caso da fila de revisão | 12 |
| Minutos para revisar uma carta pronta | 2 |

Com essas premissas: 37,6 horas por semana na planilha contra 3,1 horas com a ferramenta.
