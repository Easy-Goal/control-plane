# Próximos passos do control plane

O que já foi identificado e recomendado, mas ainda não existe. Atualize ao concluir ou ao decidir diferente.

## Regra de produto: toda plataforma, com pouca fricção

Vale para todo comando novo ou existente:

- Windows, WSL, Linux, macOS e outros Unix usam o mesmo comando, `cplane`, com a mesma saída.
- Lógica fica em Python com stdlib. Shell só onde não há como evitar: `install.sh` e `install.ps1`, que só acham o Python.
- Nada de `sudo`, instalação automática de dependência ou edição silenciosa de arquivos do usuário.
- Se faltar algo, a mensagem diz o que é e mostra o comando daquele sistema.
- O que não funciona em uma plataforma é registrado abaixo, até deixar de ser exceção.

### Exceções a eliminar

| Hoje | Falta |
|---|---|
| Guias e comandos do painel usam `shred`, `date -d`, `clip.exe` e `ssh ... bash -s` | Subcomandos do `cplane` que funcionem igual em todo sistema |
| Subir cofre e logs depende de `cp-local`, em bash, com `jq` e `curl`, e não entra no pacote | `cplane` ligar cada módulo, em Python (etapa 4) |
| Dependências opcionais do adaptador GitHub ficam em um `.venv` no repositório | Instalar por módulo, na pasta do programa |
| Docs do repositório citam `scripts/cp-*`, e o pacote não traz essas docs | Unificar em `cplane` e empacotar as docs |

## Nomes cravados ainda a remover

O programa e as docs não citam empresa, cliente ou aplicação (`panel/test_install.py` garante). Restam, fora do pacote:

| Onde | Por quê | Falta |
|---|---|---|
| `sim/` | O laboratório usa uma aplicação real como exemplo e um cliente fixo | Trocar por aplicação de exemplo e ler o cliente da configuração. Exige refazer o laboratório |
| `openbao/secrets*.toml` | A máquina atual ainda lê daqui | Remover depois de validada a instalação. O histórico antigo permanece |

## Etapa 2: máquinas, login e acesso remoto

Feita: [maquinas.md](maquinas.md). Antes de abrir na VPS, ainda falta:

- **Revisão de segurança independente** do login e do acesso remoto.
- **Testar com o Tailscale real:** o `tailscale serve` entrega o IP de origem para o `tailscale whois` e sobrescreve o `X-Forwarded-For` mandado pelo cliente? Os cabeçalhos do Serve informam a pessoa, não a máquina, e não vêm preenchidos para devices com tag. Desde a revisão de 2026-11-14, sem o IP identificado o painel remoto recusa o pedido (falha fechada). Roteiro em [maquinas.md](maquinas.md#teste-manual-pendente-com-o-tailscale-real).
- **Testar o restore** do snapshot em cofre descartável antes de promover uma VPS.
- **Sessão do cofre na principal:** hoje dura 1 h e é reaberta no terminal. Definir como fica com o painel sempre ligado.

Evoluções: passkey, identidade por chave na instalação registrada, cópia externa dos eventos, comparar nós da tailnet com a lista de dispositivos e cifrar o segredo TOTP em disco.

## Etapa 3: projetos e repositórios

- Projeto dentro de cliente existente. Hoje um projeto novo só nasce com um cliente novo.
- Repositórios por projeto, começando só com leitura: branch, último commit e versão em produção.
- Projeto: ativo, em manutenção, obsoleto ou arquivado, com motivo, data e autor. Obsoleto sai dos alertas e pode ser reativado.
- Cliente: ativo, saindo ou saiu, com motivo e checklist. Passos irreversíveis pedem confirmação à parte.
- Unificar "aplicação" e "projeto", que hoje são a mesma coisa com dois nomes.

## Etapa 4: módulos

Ligar cofre, logs e analytics um a um pelo painel, cada um sem subir os outros. Hoje a stack completa pede cerca de 2,85 GB de imagens e 630 MiB de RAM, contra 16 MiB do painel.

## Etapa 5: pessoas e avisos

Mais operadores, papéis por cliente e notificações. Cópia externa dos eventos de segurança: quem tem root na principal pode alterar o registro local.

## Distribuição

- **Download sem convite:** enquanto o repositório for privado, só quem tem acesso baixa. Decidir entre hospedagem pública do pacote ou abertura do código, para então oferecer `curl ... | sh`.
- **Assinatura do release:** a soma de verificação detecta pacote corrompido, mas não um release adulterado na origem.
- **Abrir o código:** exige repositório com histórico novo, porque o histórico atual contém nomes de clientes. Falta escolher a licença e conferir as licenças dos componentes opcionais.
- **Imagem Docker do painel:** para VPS e para quem não tiver Python.
- **Atualização:** hoje `cplane update` recebe um pacote já baixado.
- **Passkey no login:** mais resistente a phishing que TOTP. Exige verificação de assinatura, sem biblioteca na stdlib.
- **Celular:** priorizar incidentes, logs e ações rápidas. Os links das tabelas do Quadro têm só 19 a 22 px de altura.
- **Testar:** macOS, BSD, celular físico, VPS real, leitor de tela e contraste de todas as telas.
