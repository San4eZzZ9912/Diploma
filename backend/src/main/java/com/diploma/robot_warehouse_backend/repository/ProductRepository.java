package com.diploma.robot_warehouse_backend.repository;

import com.diploma.robot_warehouse_backend.entity.Product;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import java.util.List;
import java.util.Optional;

public interface ProductRepository extends JpaRepository<Product, Integer> {
    Optional<Product> findBySkuAndManufacturer(String sku, String manufacturer);

    @Query(value = """
        select distinct p.*
        from products p
        join slot_state st on st.product_id = p.product_id
        join shelf_slots sl on sl.slot_id = st.slot_id
        join shelves sh on sh.shelf_code = sl.shelf_code
        where st.occupied = true
          and st.reserved = false
          and sl.enabled = true
          and sh.role = 'STORAGE'
          and (:q is null or :q = '' or lower(p.name) like lower(concat('%', :q, '%')))
        order by p.name asc
        limit 50
    """, nativeQuery = true)
    List<Product> findInStockByNameLike(@Param("q") String q);

}
