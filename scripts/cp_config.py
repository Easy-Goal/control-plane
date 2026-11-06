"""Estado desejado: openbao/secrets.toml mais um arquivo por cliente em openbao/clients/<cliente>.toml (ADR 067).
É a única leitura desses arquivos: scripts e painel enxergam a mesma lista de clientes. Só nomes, nenhum valor."""
try:
    import tomllib
except ImportError:  # Python < 3.11: só o painel continua abrindo, sem ler o estado desejado
    tomllib = None


class ConfigError(Exception):
    pass


def load(main_path, clients_dir=None):
    data = tomllib.loads(main_path.read_text(encoding="utf-8"))
    clients = data.setdefault("client", [])
    seen = {c["slug"] for c in clients}
    if clients_dir is None or not clients_dir.is_dir():
        return data
    for path in sorted(clients_dir.glob("*.toml")):
        extra = tomllib.loads(path.read_text(encoding="utf-8")).get("client", [])
        if len(extra) != 1 or extra[0].get("slug") != path.stem:
            raise ConfigError(f"{path.name}: precisa declarar um único [[client]], com slug = \"{path.stem}\"")
        if path.stem in seen:
            raise ConfigError(f"{path.name}: o cliente {path.stem} já existe em outro arquivo")
        seen.add(path.stem)
        clients.append(extra[0])
    return data
