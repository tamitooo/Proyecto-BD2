class _Bucket:
    def __init__(self, local_depth):
        self.local_depth = local_depth
        self.records = {}

    def distinct_keys(self):
        return len(self.records)

    def entry_count(self):
        return sum(len(values) for values in self.records.values())


class ExtendibleHash:

    def __init__(
        self,
        bucket_capacity=4,
        unique=False,
        hash_func=None,
        max_depth=64,
    ):
        if bucket_capacity < 1:
            raise ValueError("bucket_capacity must be >= 1")
        if max_depth < 1:
            raise ValueError("max_depth must be >= 1")

        self.bucket_capacity = bucket_capacity
        self.unique = unique
        self.hash_func = hash_func or hash
        self.max_depth = max_depth

        # Se inicia con profundidad global 1 y dos buckets independientes.
        self.global_depth = 1
        self.directory = [
            _Bucket(local_depth=1),
            _Bucket(local_depth=1),
        ]

        # Cantidad total de pares (key, value), incluyendo duplicados.
        self._size = 0

    def __len__(self):
        return self._size

    def _hash(self, key):
        """
        Normaliza el hash a un entero no negativo de 64 bits.
        """
        return self.hash_func(key) & ((1 << 64) - 1)

    def _directory_index(self, key):
        mask = (1 << self.global_depth) - 1
        return self._hash(key) & mask

    def _bucket_for(self, key):
        return self.directory[self._directory_index(key)]

    def _unique_buckets(self):
        seen = set()
        buckets = []

        for bucket in self.directory:
            bucket_id = id(bucket)
            if bucket_id not in seen:
                seen.add(bucket_id)
                buckets.append(bucket)

        return buckets

    def search(self, key):
        """
        Retorna todos los valores asociados a una clave exacta.
        """
        bucket = self._bucket_for(key)
        return list(bucket.records.get(key, []))

    def contains(self, key):
        return bool(self.search(key))

    def insert(self, key, value):
        """
        Inserta un par (key, value).

        Si la clave ya existe:
          - unique=True  -> lanza ValueError.
          - unique=False -> agrega otro valor bajo la misma clave.

        Si el bucket esta lleno, realiza split y, si es necesario,
        duplica el directorio.
        """
        while True:
            bucket = self._bucket_for(key)

            if key in bucket.records:
                if self.unique:
                    raise ValueError(f"duplicate hash key: {key}")

                bucket.records[key].append(value)
                self._size += 1
                return

            if bucket.distinct_keys() < self.bucket_capacity:
                bucket.records[key] = [value]
                self._size += 1
                return

            self._split_bucket(bucket)

    def bulk_load(self, entries):
        """
        Inserta una coleccion de pares (key, value).
        """
        for key, value in entries:
            self.insert(key, value)

    def _double_directory(self):
        if self.global_depth >= self.max_depth:
            raise OverflowError(
                "maximum extendible-hash directory depth reached"
            )

        # Los nuevos indices conservan las referencias anteriores y agregan
        # una copia con el nuevo bit mas significativo del directorio.
        self.directory = self.directory + self.directory[:]
        self.global_depth += 1

    def _split_bucket(self, bucket):
        old_depth = bucket.local_depth

        if old_depth >= self.max_depth:
            raise OverflowError(
                "maximum bucket local depth reached; "
                "hash values cannot be separated"
            )

        if old_depth == self.global_depth:
            self._double_directory()

        new_depth = old_depth + 1
        new_bucket = _Bucket(local_depth=new_depth)
        bucket.local_depth = new_depth

        split_bit = 1 << old_depth

        # Redirigir la mitad de las entradas del directorio que apuntaban
        # al bucket original hacia el nuevo bucket.
        for index, current in enumerate(self.directory):
            if current is bucket and (index & split_bit):
                self.directory[index] = new_bucket

        # Redistribuir las claves segun los nuevos bits del directorio.
        old_records = bucket.records
        bucket.records = {}

        for key, values in old_records.items():
            target = self._bucket_for(key)
            target.records[key] = values

        # Detecta el caso patologico en el que todas las claves siguen
        # cayendo en el mismo bucket por colisiones de hash. El proximo
        # insert volvera a dividir hasta max_depth o hasta separarlas.

    def delete(self, key, value=None):
        """
        Elimina entradas del hash.

        - delete(key): elimina todos los valores asociados.
        - delete(key, value): elimina solo una ocurrencia de ese valor.

        Despues intenta combinar buckets compatibles y reducir el directorio.
        """
        index = self._directory_index(key)
        bucket = self.directory[index]

        if key not in bucket.records:
            return False

        values = bucket.records[key]

        if value is None:
            self._size -= len(values)
            del bucket.records[key]
        else:
            try:
                values.remove(value)
            except ValueError:
                return False

            self._size -= 1

            if not values:
                del bucket.records[key]

        self._try_merge(index)
        self._shrink_directory()
        return True

    def _try_merge(self, directory_index):
        """
        Combina recursivamente un bucket con su buddy cuando:
          - tienen la misma local_depth;
          - la suma de claves distintas cabe en un bucket.
        """
        bucket = self.directory[directory_index]

        while bucket.local_depth > 1:
            depth = bucket.local_depth
            buddy_bit = 1 << (depth - 1)
            buddy_index = directory_index ^ buddy_bit
            buddy = self.directory[buddy_index]

            if buddy is bucket:
                break

            if buddy.local_depth != depth:
                break

            combined_keys = (
                bucket.distinct_keys() + buddy.distinct_keys()
            )
            if combined_keys > self.bucket_capacity:
                break

            # Sobrevive el bucket cuyo bit diferenciador es 0.
            if directory_index & buddy_bit:
                survivor = buddy
                removed = bucket
                directory_index = buddy_index
            else:
                survivor = bucket
                removed = buddy

            for key, values in removed.records.items():
                if key in survivor.records:
                    survivor.records[key].extend(values)
                else:
                    survivor.records[key] = values

            survivor.local_depth = depth - 1

            for i, current in enumerate(self.directory):
                if current is bucket or current is buddy:
                    self.directory[i] = survivor

            bucket = survivor

    def _shrink_directory(self):
        """
        Reduce global_depth mientras las dos mitades del directorio sean
        equivalentes y ningun bucket requiera la profundidad actual.
        """
        while self.global_depth > 1:
            half = len(self.directory) // 2

            if any(
                self.directory[i] is not self.directory[i + half]
                for i in range(half)
            ):
                break

            if any(
                bucket.local_depth == self.global_depth
                for bucket in self._unique_buckets()
            ):
                break

            self.directory = self.directory[:half]
            self.global_depth -= 1

    def items(self):
        """
        Retorna todos los pares (key, value).

        No existe garantia de orden, a diferencia de un B+ Tree.
        """
        result = []

        for bucket in self._unique_buckets():
            for key, values in bucket.records.items():
                for value in values:
                    result.append((key, value))

        return result

    def keys(self):
        """
        Retorna las claves distintas almacenadas, sin garantia de orden.
        """
        result = []

        for bucket in self._unique_buckets():
            result.extend(bucket.records.keys())

        return result

    def bucket_count(self):
        return len(self._unique_buckets())

    def stats(self):
        """
        Metricas utiles para debugging y benchmarks.
        """
        buckets = self._unique_buckets()
        distinct_keys = sum(bucket.distinct_keys() for bucket in buckets)

        return {
            "global_depth": self.global_depth,
            "directory_size": len(self.directory),
            "bucket_count": len(buckets),
            "bucket_capacity": self.bucket_capacity,
            "distinct_keys": distinct_keys,
            "entries": self._size,
            "load_factor": (
                distinct_keys / (len(buckets) * self.bucket_capacity)
                if buckets
                else 0.0
            ),
        }

    def validate(self):
        """
        Verifica las invariantes principales de Extendible Hashing.
        """
        if len(self.directory) != (1 << self.global_depth):
            raise AssertionError(
                "directory size does not match global depth"
            )

        buckets = self._unique_buckets()
        total_entries = 0

        for bucket in buckets:
            if bucket.local_depth < 1:
                raise AssertionError("bucket local depth must be >= 1")

            if bucket.local_depth > self.global_depth:
                raise AssertionError(
                    "bucket local depth exceeds global depth"
                )

            if bucket.distinct_keys() > self.bucket_capacity:
                raise AssertionError("bucket exceeds capacity")

            references = [
                index
                for index, current in enumerate(self.directory)
                if current is bucket
            ]

            expected_references = 1 << (
                self.global_depth - bucket.local_depth
            )

            if len(references) != expected_references:
                raise AssertionError(
                    "bucket has an invalid number of directory references"
                )

            # Todas las referencias a un bucket deben compartir sus
            # local_depth bits menos significativos.
            mask = (1 << bucket.local_depth) - 1
            prefix = references[0] & mask

            for index in references:
                if (index & mask) != prefix:
                    raise AssertionError(
                        "directory references violate bucket prefix"
                    )

            for key, values in bucket.records.items():
                if not values:
                    raise AssertionError("key has no associated values")

                expected_bucket = self._bucket_for(key)
                if expected_bucket is not bucket:
                    raise AssertionError(
                        "key stored in incorrect hash bucket"
                    )

                if self.unique and len(values) != 1:
                    raise AssertionError(
                        "duplicate values in unique hash index"
                    )

                total_entries += len(values)

        if total_entries != self._size:
            raise AssertionError(
                "stored entry count does not match hash size"
            )

        return True
