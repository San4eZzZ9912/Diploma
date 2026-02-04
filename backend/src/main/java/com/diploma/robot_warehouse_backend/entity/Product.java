package com.diploma.robot_warehouse_backend.entity;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;

import java.util.List;

@Entity
@Table(name = "products")
@Getter
@NoArgsConstructor
public class Product {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "product_id")
    private Integer id;

    @Column(nullable = false)
    private String sku;

    @Column(nullable = false)
    private String manufacturer;

    @Column(nullable = false)
    private String name;

    @OneToMany(mappedBy = "product")
    private List<InboundLine> inboundLines;

    @OneToMany(mappedBy = "product")
    private List<Task> tasks;

    public Product(String sku, String manufacturer, String name) {
        this.sku = sku;
        this.manufacturer = manufacturer;
        this.name = name;
    }

}
