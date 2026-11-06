# Roteiro do vídeo de demonstração (2 minutos)

## Roteiro por extenso

**[0:00 a 0:15] Abertura, no topo do site.**
Todo marketplace de delivery repassa dinheiro aos restaurantes toda semana. Do valor das vendas saem comissão, taxa de pagamento, cupons e estornos. O financeiro confere isso em planilha, linha a linha. Eu construí uma ferramenta que faz essa conferência e explica cada diferença.

**[0:15 a 0:35] Os números, ainda no topo.**
Montei um marketplace fictício com 200 restaurantes e 63.825 pedidos em um mês, e plantei 150 erros de dez tipos, com gabarito. A ferramenta detectou todos e confirmou 145 sozinha, com a causa certa, sem nenhuma confirmação errada. Plantei também 1.908 armadilhas, coisas que parecem erro e não são. Nenhuma virou alerta falso.

**[0:35 a 0:55] Como funciona.**
A regra de ouro: a IA não faz conta. O dinheiro é calculado em código, em centavos inteiros, com o contrato vigente na data de cada pedido. As regras resolvem a maior parte. A IA entra só onde foi melhor que a regra no teste: ler a nota do atendimento num estorno sem responsável. E roda na minha máquina, sem API e sem chave.

**[0:55 a 1:30] A demo.**
Escolho uma semana e um restaurante. Aqui está o devido pelo contrato, o que veio no extrato e o que caiu no banco. Esta divergência é um cupom da plataforma cobrado do restaurante. Abro as evidências: o pedido, a linha do extrato, o contrato e o recálculo. Neste outro caso, a IA leu a nota do atendimento e citou o trecho que decide. Quando ela não tem certeza, ou quando a regra e a IA discordam, o caso vai para a fila de revisão humana. Esta é a carta para o restaurante, montada pelo código. Eu testei a IA escrevendo essa explicação e li 20 cartas: 12 tinham fato errado. Então ela ficou desligada nessa parte.

**[1:30 a 1:50] Resultados.**
Precisão e revocação por tipo de erro, falsos positivos por armadilha e a comparação honesta entre regra e IA. Nos 68 casos ambíguos, só com regras eram 33 certos e 7 errados; com a IA local, 50 certos e nenhum errado. E onde a IA não ajudou, nas linhas com mais de uma causa possível, nas cartas e no resumo da semana, a decisão ficou com o código. Na calculadora, com premissas que dá para mudar, a estimativa é de 34,5 horas por semana a menos de trabalho manual.

**[1:50 a 2:00] Fechamento.**
Os dados são sintéticos, então o próximo passo seria rodar em paralelo à planilha com dados reais. O código, os testes e o roteiro para reproduzir estão no repositório.

## Cola para a gravação

* Problema: conferência do repasse semanal em planilha, linha a linha.
* Dados: 200 restaurantes, 63.825 pedidos, 150 erros plantados, 1.908 armadilhas.
* Detecção: todos os 150. Confirmados sozinhos com a causa certa: 145, sem nenhum errado.
* Alertas falsos: 0 em 1.908.
* IA: só para classificar o ambíguo, local, sem API, nunca faz conta, cita evidência, incerteza vai para revisão.
* Cartas: 20 lidas, 12 com fato errado quando escritas pela IA; ficaram com o código.
* Ambíguos: regra 33 certos e 7 errados; regra e IA 50 certos e 0 errados.
* Horas: 34,5 por semana, estimativa com premissas editáveis.
* Limite: dados sintéticos; próximo passo é rodar em paralelo com dados reais.
