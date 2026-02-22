package com.diploma.robot_warehouse_backend.entity;

import com.diploma.robot_warehouse_backend.enums.Status;
import com.diploma.robot_warehouse_backend.enums.Type;
import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import java.time.LocalDateTime;

@Entity
@Table(name = "tasks")
@Getter
@NoArgsConstructor
public class Task {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "task_id")
    private Integer id;

    @Enumerated(EnumType.STRING)
    @Column(name = "status", nullable = false)
    @Setter
    private Status status;

    @Enumerated(EnumType.STRING)
    @Column(name = "type", nullable = false)
    @Setter
    private Type type;

    @Column(name = "robot_id")
    @Setter
    private String robotId;

    @Column(name = "observed_sku")
    @Setter
    private String observedSku;

    @Column(name = "observed_manufacturer")
    @Setter
    private String observedManufacturer;

    @Column(name = "created_at", nullable = false)
    private LocalDateTime createdAt;

    @Column(name = "updated_at")
    @Setter
    private LocalDateTime updatedAt;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "inbound_line_id", nullable = false)
    private InboundLine inboundLine;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "product_id", nullable = false)
    private Product product;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "source_slot_id")
    @Setter
    private ShelfSlot sourceSlot;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "target_slot_id")
    @Setter
    private ShelfSlot targetSlot;

    public Task(Status status, InboundLine inboundLine, Product product) {
        this.status = status;
        this.inboundLine = inboundLine;
        this.product = product;
        this.createdAt = LocalDateTime.now();
        this.type = Type.PUTAWAY;
    }
}
