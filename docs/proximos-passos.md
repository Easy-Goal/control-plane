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

## Etapa 2: máquinas, login e acesso remoto

- Tela Máquinas: instalações (principal, lab, teste) e dispositivos (Operação, Consulta, Lab/teste), com dono, aprovado por e último acesso.
- Aprovação por código: device novo fica aguardando; quem já é aprovado, ou o terminal da principal, decide a classe.
- Token por dispositivo, com só o hash no servidor; revogação imediata; classe aplicada pelo servidor.
- Login com senha e TOTP próprios do painel (`hashlib.scrypt`, `hmac`), com códigos de recuperação. **Exige revisão de segurança antes de abrir na VPS.**
- MFA novamente para ação em produção.
- Alertas: device desconhecido, token revogado em uso, falhas de MFA, device novo aprovado, ação em produção com o device que agiu.
- Impor uma única principal por conta. Hoje `cplane machine promote` só registra o papel.
- Acesso pela tailnet, com `tailscale serve`. Testar antes se o backend recebe o IP de origem para consultar `tailscale whois`: os cabeçalhos do Serve informam a pessoa, não a máquina, e não vêm preenchidos para devices com tag.
- Cofre em outra máquina: o device consulta a principal, sem copiar valores.
- Testar o restore do snapshot em cofre descartável antes de promover uma VPS.

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
- **Passkey no login:** mais resistente a phishing que TOTP. Exige HTTPS e verificação de assinatura, sem biblioteca na stdlib.
- **Celular:** priorizar incidentes, logs e ações rápidas. Os links das tabelas do Quadro têm só 19 a 22 px de altura.
- **Testar:** macOS, BSD, celular físico, VPS real, leitor de tela e contraste de todas as telas.
