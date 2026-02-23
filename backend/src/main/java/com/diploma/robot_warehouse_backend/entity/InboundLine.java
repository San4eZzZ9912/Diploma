package com.diploma.robot_warehouse_backend.entity;

import com.diploma.robot_warehouse_backend.enums.Status;
import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import org.hibernate.annotations.CreationTimestamp;

import java.time.LocalDateTime;
import java.util.List;

@Entity
@Table(name = "inbound_lines")
@Getter
@NoArgsConstructor
public class InboundLine {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "inbound_line_id")
    private Integer id;

    @Column(nullable = false)
    private Integer quantity;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private Status status;

    @CreationTimestamp
    @Column(name = "created_at", nullable = false)
    private LocalDateTime createdAt;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "product_id", nullable = false)
    private Product product;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "inbound_id", nullable = false)
    private Inbound inbound;

    @OneToMany(mappedBy = "inboundLine")
    private List<Task> tasks;

    public InboundLine(Inbound inbound, Product product, Integer quantity) {
        this.inbound = inbound;
        this.product = product;
        this.quantity = quantity;
        this.status = Status.NEW;
        this.createdAt = LocalDateTime.now();
    }
}
