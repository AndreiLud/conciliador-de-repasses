# Log de qualidade dos dados

Saída de `python run_all.py`. Cada linha é uma verificação feita na ingestão, com a decisão tomada e o motivo.

| Arquivo | Verificação | Resultado | Quantidade | Decisão | Justificativa |
|---|---|---|---|---|---|
| pedidos.csv | colunas obrigatórias presentes | ok | 0 | nenhuma | 14 colunas |
| pedidos.csv | linhas idênticas repetidas | corrigido | 12 | mantida uma cópia de cada | linhas 100% iguais são falha de exportação, não pedidos distintos |
| pedidos.csv | pedido_id único | ok | 0 | nenhuma | mesmo id com conteúdo diferente exige correção na origem |
| pedidos.csv | restaurante_id fora do padrão (minúsculas ou espaços) | corrigido | 131 | convertido para maiúsculas sem espaços | o cadastro usa o padrão R0000 |
| pedidos.csv | forma de pagamento com grafia variada | corrigido | 1963 | normalizada para pix, credito, debito ou vale_refeicao | a mesma forma aparece com acento, maiúsculas ou abreviação |
| pedidos.csv | status fora do domínio | ok | 0 | nenhuma |  |
| pedidos.csv | pedido entregue sem data de conclusão | ok | 0 | nenhuma |  |
| pedidos.csv | pedido cancelado sem data de cancelamento | ok | 0 | nenhuma |  |
| pedidos.csv | valores negativos | ok | 0 | nenhuma |  |
| pedidos.csv | cupom sem indicação de quem paga | ok | 0 | nenhuma |  |
| pedidos.csv | valor_total = itens + entrega − cupom | ok | 0 | nenhuma | o total pago é a base da taxa de pagamento |
| pedidos.csv | pedidos válidos após limpeza | ok | 0 | 63825 pedidos de 63837 linhas lidas |  |
| estornos.csv | motivo com espaços sobrando | corrigido | 140 | espaços removidos | não muda o conteúdo |
| estornos.csv | estorno_id único | ok | 0 | nenhuma |  |
| estornos.csv | estorno de pedido inexistente | ok | 0 | nenhuma |  |
| estornos.csv | estornos somados acima do valor do pedido | ok | 0 | nenhuma |  |
| estornos.csv | responsável fora de restaurante ou plataforma | ok | 0 | tratado como não preenchido e decidido pela nota | um rótulo desconhecido não pode virar isenção |
| estornos.csv | estorno sem responsável preenchido | aviso | 209 | mantido; o dono é decidido pela nota do atendimento | palavra-chave quando é claro, modelo de linguagem quando não é, revisão humana se a confiança for baixa |
| estornos.csv | pedidos com mais de um estorno | ok | 10 | mantidos; cada estorno tem id próprio | estorno complementar é legítimo |
| repasse_extrato.csv | linhas de pedido sem componentes (layout legado) | aviso | 16215 | marcadas como layout legado; só o líquido é comparável | restaurantes do sistema antigo recebem só o valor líquido e uma descrição |
| repasse_extrato.csv | linha_id único | ok | 0 | nenhuma |  |
| repasse_extrato.csv | tipo_linha fora do domínio | ok | 0 | nenhuma |  |
| repasse_extrato.csv | líquido = soma dos componentes (layout detalhado) | ok | 0 | nenhuma |  |
| repasse_extrato.csv | linha de pedido ou estorno sem pedido_id | ok | 0 | nenhuma |  |
| repasse_extrato.csv | ajuste manual sem chamado ou justificativa | ok | 0 | nenhuma |  |
| repasses.csv | repasse_id único | ok | 0 | nenhuma |  |
| repasses.csv | total do repasse = soma das linhas do extrato | ok | 0 | nenhuma |  |
| repasses.csv | quantidade de linhas confere com o extrato | ok | 0 | nenhuma |  |
| repasses.csv | semanas de segunda a domingo, uma linha por semana | ok | 0 | nenhuma | o calendário do repasse vem do próprio arquivo |
| extrato_bancario.csv | cabeçalho do banco antes da tabela | corrigido | 6 | linhas de identificação ignoradas | o arquivo traz nome do banco, cliente e período antes das colunas |
| extrato_bancario.csv | rodapé e linhas sem data | corrigido | 3 | ignoradas | saldo final e avisos do banco não são lançamentos |
| extrato_bancario.csv | saldo corrente bate lançamento a lançamento | ok | 0 | nenhuma | confirma que nenhuma linha se perdeu na leitura |
| extrato_bancario.csv | codificação latin-1 e valores no formato 1.234,56 | ok | 0 | 1144 lançamentos lidos |  |
| contratos.xlsx | nome de plano com espaços sobrando | corrigido | 1 | espaços removidos |  |
| contratos.xlsx | taxas do Excel convertidas para pontos-base inteiros | ok | 0 | arredondamento para o ponto-base mais próximo, recusando sobra maior que 0,0001 | células de porcentagem são números binários (0,0319 vira 0,031899...) |
| contratos.xlsx | versões de plano sem sobreposição de vigência | ok | 0 | nenhuma |  |
| contratos.xlsx | plano_id em minúsculas na aba restaurante_plano | corrigido | 6 | convertido para maiúsculas |  |
| contratos.xlsx | restaurante com plano inexistente | ok | 0 | nenhuma |  |
| contratos.xlsx | vigências de plano por restaurante sem sobreposição nem buraco | ok | 0 | nenhuma | cada pedido precisa de exatamente um contrato |
| contratos.xlsx | restaurantes com troca de plano no período | ok | 20 | contrato aplicado pela data de criação do pedido |  |
| contratos.xlsx | restaurante_id único no cadastro | ok | 0 | nenhuma |  |
| contratos.xlsx | restaurante sem contrato | ok | 0 | nenhuma |  |
| contratos.xlsx | nomes fantasia quase iguais (segunda unidade) | aviso | 16 | mantidos; o casamento bancário compara também CNPJ, agência e conta | segunda unidade com o mesmo nome é comum |
| contratos.xlsx | nomes do cadastro no padrão do banco | ok | 0 | maiúsculas, sem acento e com as abreviações usadas pelo banco | permite comparar o histórico do extrato com o nome fantasia e a razão social |
| pedidos.csv | pedido de restaurante fora do cadastro | ok | 0 | nenhuma |  |
