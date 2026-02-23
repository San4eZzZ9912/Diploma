package com.diploma.robot_warehouse_backend.entity;

import com.diploma.robot_warehouse_backend.enums.Status;
import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import org.hibernate.annotations.CreationTimestamp;

import java.time.LocalDateTime;
import java.util.List;

@Entity
@Table(name = "inbounds")
@Getter
@NoArgsConstructor
public class Inbound {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "inbound_id")
    private Integer id;

    @Column(name = "source")
    private String source;

    @Column(name = "external_ref")
    private String externalRef;

    @Column(name = "file_name")
    private String fileName;

    @Enumerated(EnumType.STRING)
    @Column(name = "status", nullable = false)
    private Status status;

    @CreationTimestamp
    @Column(name = "created_at", nullable = false, updatable = false)
    private LocalDateTime createdAt;

    @OneToMany(mappedBy = "inbound")
    private List<InboundLine> inboundLines;

    public Inbound(String source, String externalRef, String fileName, Status status) {
        this.source = source;
        this.externalRef = externalRef;
        this.fileName = fileName;
        this.status = status;
        this.createdAt = LocalDateTime.now();
    }
}
