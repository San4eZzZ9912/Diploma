package com.diploma.robot_warehouse_backend.entity;


import com.diploma.robot_warehouse_backend.enums.Status;
import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;
import java.util.List;

@Entity
@Getter
@Table(name = "outbound_lines")
@NoArgsConstructor
public class OutboundLine {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "outbound_line_id", nullable = false)
    private Integer id;

    @Column(nullable = false)
    private Integer quantity;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private Status status;

    @Column(name = "created_at", nullable = false)
    private LocalDateTime createdAt;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "outbound_id", nullable = false)
    private Outbound outbound;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "product_id", nullable = false)
    private Product product;

    @OneToMany(mappedBy = "outboundLine")
    private List<Task> tasks;

    public OutboundLine(Outbound outbound, Product product, Integer quantity) {
        this.outbound = outbound;
        this.product = product;
        this.quantity = quantity;
        this.createdAt = LocalDateTime.now();
        this.status = Status.NEW;
    }
}
