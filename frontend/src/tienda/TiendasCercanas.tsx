interface Props {
  productoId: number;
}

export default function TiendasCercanas({ productoId }: Props) {
  return (
    <section className="panel" aria-labelledby="tiendas-cercanas">
      <h3 id="tiendas-cercanas" className="panel__title">Tiendas cercanas</h3>
      <p className="panel__hint">
        Aquí irán las tiendas más cercanas con stock del producto {productoId} y su mapa (#137).
      </p>
    </section>
  );
}
